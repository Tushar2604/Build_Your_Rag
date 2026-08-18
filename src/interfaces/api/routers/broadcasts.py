"""WhatsApp broadcast campaigns — outbound sends with auto-reply.

Admin CRUD plus campaign controls (start / pause / retry failed / mark
completed), the contacts list the console paginates and filters, per-recipient
chat logs, and human takeover. The Twilio status callback is public and
signature-verified, exactly like the inbound message webhook.

Sends run as BackgroundTasks: a campaign of 500 contacts takes minutes, so the
request that starts it returns immediately and the console polls for progress.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query, Request, Response

from src.application.use_cases.broadcast import (
    AddBroadcastRecipients,
    SendBroadcast,
    parse_contacts,
)
from src.config.container import get_container
from src.config.settings import get_settings
from src.domain.broadcast.entities import Broadcast
from src.domain.chat.entities import Message, MessageRole
from src.domain.shared.identifiers import ChatbotId, SessionId, TenantId
from src.infrastructure.messaging.twilio_signature import verify_twilio_signature
from src.interfaces.api.deps import AdminPrincipalDep, ContainerDep
from src.interfaces.api.schemas import (
    AddRecipientsRequest,
    AddRecipientsResponse,
    BroadcastMessageResponse,
    BroadcastRecipientResponse,
    BroadcastResponse,
    CampaignSenderResponse,
    CreateBroadcastRequest,
    PreviewContactsRequest,
    PreviewContactsResponse,
    PreviewedContact,
    RecipientPageResponse,
    SendManualMessageRequest,
)

router = APIRouter(prefix="/broadcasts", tags=["broadcasts"])

# Twilio's MessageStatus vocabulary mapped onto our funnel. Statuses we don't
# model (`queued`, `accepted`, `sending`) are intentionally absent — they'd move
# a recipient backwards from `sent`, and advance_to would reject them anyway.
_TWILIO_STATUS_MAP = {
    "sent": "sent",
    "delivered": "delivered",
    "read": "read",
    "failed": "failed",
    "undelivered": "failed",
}


def _status_callback_url() -> str:
    return f"{get_settings().app_base_url.rstrip('/')}/api/v1/broadcasts/status-callback"


def _to_response(b: Broadcast, chatbot_name: str, from_number: str) -> BroadcastResponse:
    return BroadcastResponse(
        id=b.id,
        chatbot_id=b.chatbot_id,
        chatbot_name=chatbot_name,
        whatsapp_channel_id=b.whatsapp_channel_id,
        whatsapp_session_id=b.whatsapp_session_id,
        sender_kind=b.sender_kind,  # type: ignore[arg-type]
        mode=b.mode,  # type: ignore[arg-type]
        from_number=from_number,
        name=b.name,
        message_template=b.message_template,
        status=b.status,  # type: ignore[arg-type]
        total_count=b.total_count,
        sent_count=b.sent_count,
        delivered_count=b.delivered_count,
        read_count=b.read_count,
        replied_count=b.replied_count,
        failed_count=b.failed_count,
        created_at=b.created_at,
        updated_at=b.updated_at,
    )


def _recipient_response(r) -> BroadcastRecipientResponse:
    return BroadcastRecipientResponse(
        id=r.id,
        phone_number=r.phone_number,
        display_name=r.display_name,
        status=r.status,
        error=r.error,
        session_id=r.session_id,
        attempts=r.attempts,
        updated_at=r.updated_at,
    )


async def _run_send(tenant_id: TenantId, broadcast_id: uuid.UUID) -> None:
    """Background entrypoint — builds its own container (no request scope)."""
    container = get_container()
    use_case = SendBroadcast(
        container.unit_of_work(),
        container.whatsapp_sender,
        _status_callback_url(),
        bridge=container.whatsapp_bridge,
    )
    await use_case.execute(tenant_id, broadcast_id)


async def _load(uow, tenant_id: TenantId, broadcast_id: uuid.UUID) -> Broadcast:
    broadcast = await uow.broadcasts.get(tenant_id, broadcast_id)
    if broadcast is None:
        raise HTTPException(status_code=404, detail="Campaign not found")
    return broadcast


async def _decorate(uow, tenant_id: TenantId, broadcast: Broadcast) -> BroadcastResponse:
    """Attach the display names a campaign row needs.

    The from-number lives in a different table per sender kind, so this resolves
    whichever one applies rather than assuming a Cloud API channel.
    """
    bot = await uow.chatbots.get(tenant_id, broadcast.chatbot_id)
    from_number = ""
    if broadcast.sender_kind == "cloud_api" and broadcast.whatsapp_channel_id:
        channel = await uow.whatsapp_channels.get(tenant_id, broadcast.whatsapp_channel_id)
        from_number = channel.phone_number if channel else ""
    elif broadcast.whatsapp_session_id:
        session = await uow.whatsapp_web_sessions.get(tenant_id, broadcast.whatsapp_session_id)
        from_number = session.phone_number if session else ""
    return _to_response(
        broadcast,
        bot.name if bot else "Unknown assistant",
        from_number,
    )


@router.get("/senders", response_model=list[CampaignSenderResponse])
async def list_senders(
    principal: AdminPrincipalDep, container: ContainerDep
) -> list[CampaignSenderResponse]:
    """Every WhatsApp number this workspace can send a campaign from.

    Both kinds in one list, each flagged with whether it can actually send right
    now. Unavailable senders are listed rather than hidden — "my number isn't
    there" is a much harder problem to debug than "my number says it needs
    re-linking".
    """
    bridge_ready = container.whatsapp_bridge.enabled
    senders: list[CampaignSenderResponse] = []

    async with container.unit_of_work() as uow:
        uow.set_tenant_scope(principal.tenant_id)
        channels = await uow.whatsapp_channels.list_for_tenant(principal.tenant_id)
        sessions = await uow.whatsapp_web_sessions.list_for_tenant(principal.tenant_id)
        names: dict[str, str] = {}
        for bot in await uow.chatbots.list_for_tenant(principal.tenant_id):
            names[str(bot.id)] = bot.name

    for channel in channels:
        senders.append(
            CampaignSenderResponse(
                id=channel.id,
                kind="cloud_api",
                label=f"{channel.phone_number} · Cloud API",
                phone_number=channel.phone_number,
                available=True,
                chatbot_id=channel.chatbot_id,
                chatbot_name=names.get(str(channel.chatbot_id), ""),
            )
        )

    for session in sessions:
        linked = session.status == "linked"
        reason = ""
        if not bridge_ready:
            reason = "The WhatsApp bridge isn't running on this server."
        elif not linked:
            reason = "This phone isn't linked — scan the QR under WhatsApp Numbers."
        senders.append(
            CampaignSenderResponse(
                id=session.id,
                kind="personal",
                label=(
                    f"{session.phone_number or session.display_name or 'Personal WhatsApp'}"
                    " · Phone WhatsApp"
                ),
                phone_number=session.phone_number,
                available=linked and bridge_ready,
                unavailable_reason=reason,
                chatbot_id=session.chatbot_id,
                chatbot_name=names.get(str(session.chatbot_id), ""),
            )
        )

    return senders


@router.post("", response_model=BroadcastResponse, status_code=201)
async def create_broadcast(
    body: CreateBroadcastRequest, principal: AdminPrincipalDep, container: ContainerDep
) -> BroadcastResponse:
    """Create a campaign in `queued`. Nothing is sent until /start — an operator
    should be able to load a list and review it before it goes out."""
    async with container.unit_of_work() as uow:
        uow.set_tenant_scope(principal.tenant_id)
        bot = await uow.chatbots.get(principal.tenant_id, ChatbotId(body.chatbot_id))
        if bot is None:
            raise HTTPException(status_code=404, detail="Chatbot not found")
        channel_id: uuid.UUID | None = None
        session_id: uuid.UUID | None = None
        sender_kind = body.sender_kind or "cloud_api"

        if body.sender_id is not None and body.sender_kind == "personal":
            session = await uow.whatsapp_web_sessions.get(principal.tenant_id, body.sender_id)
            if session is None:
                raise HTTPException(status_code=404, detail="That WhatsApp number wasn't found.")
            if session.status != "linked":
                raise HTTPException(
                    status_code=400,
                    detail="That phone isn't linked right now — scan the QR under "
                    "WhatsApp Numbers, then try again.",
                )
            session_id = session.id
        elif body.sender_id is not None:
            channel = await uow.whatsapp_channels.get(principal.tenant_id, body.sender_id)
            if channel is None:
                raise HTTPException(status_code=404, detail="That WhatsApp number wasn't found.")
            channel_id = channel.id
        else:
            # No sender chosen — use the one already bound to this assistant,
            # which is how campaigns worked before senders were selectable.
            channel = await uow.whatsapp_channels.get_by_chatbot(
                principal.tenant_id, ChatbotId(body.chatbot_id)
            )
            if channel is None:
                raise HTTPException(
                    status_code=400,
                    detail="Choose a WhatsApp number to send from, or connect one to this "
                    "assistant first (Phone Numbers → Connect WhatsApp).",
                )
            channel_id = channel.id

        broadcast = Broadcast(
            tenant_id=principal.tenant_id,
            chatbot_id=ChatbotId(body.chatbot_id),
            whatsapp_channel_id=channel_id,
            whatsapp_session_id=session_id,
            sender_kind=sender_kind,
            mode=body.mode,
            name=body.name.strip(),
            message_template=body.message_template.strip(),
        )
        if (error := broadcast.validation_error()) is not None:
            raise HTTPException(status_code=400, detail=error)
        await uow.broadcasts.add(broadcast)
        await uow.commit()

    if body.recipients or body.recipients_text:
        use_case = AddBroadcastRecipients(container.unit_of_work())
        await use_case.execute(
            principal.tenant_id,
            broadcast.id,
            structured=[(r.phone_number, r.display_name) for r in body.recipients],
            text_blob=body.recipients_text,
        )

    async with container.unit_of_work() as uow:
        uow.set_tenant_scope(principal.tenant_id)
        broadcast = await _load(uow, principal.tenant_id, broadcast.id)
        return await _decorate(uow, principal.tenant_id, broadcast)


@router.get("", response_model=list[BroadcastResponse])
async def list_broadcasts(
    principal: AdminPrincipalDep, container: ContainerDep
) -> list[BroadcastResponse]:
    async with container.unit_of_work() as uow:
        uow.set_tenant_scope(principal.tenant_id)
        broadcasts = await uow.broadcasts.list_for_tenant(principal.tenant_id)
        return [await _decorate(uow, principal.tenant_id, b) for b in broadcasts]


@router.get("/{broadcast_id}", response_model=BroadcastResponse)
async def get_broadcast(
    broadcast_id: uuid.UUID, principal: AdminPrincipalDep, container: ContainerDep
) -> BroadcastResponse:
    async with container.unit_of_work() as uow:
        uow.set_tenant_scope(principal.tenant_id)
        broadcast = await _load(uow, principal.tenant_id, broadcast_id)
        return await _decorate(uow, principal.tenant_id, broadcast)


@router.delete("/{broadcast_id}", status_code=204)
async def delete_broadcast(
    broadcast_id: uuid.UUID, principal: AdminPrincipalDep, container: ContainerDep
) -> None:
    async with container.unit_of_work() as uow:
        uow.set_tenant_scope(principal.tenant_id)
        await uow.broadcasts.delete(principal.tenant_id, broadcast_id)
        await uow.commit()


@router.post("/{broadcast_id}/recipients", response_model=AddRecipientsResponse)
async def add_recipients(
    broadcast_id: uuid.UUID,
    body: AddRecipientsRequest,
    principal: AdminPrincipalDep,
    container: ContainerDep,
) -> AddRecipientsResponse:
    async with container.unit_of_work() as uow:
        uow.set_tenant_scope(principal.tenant_id)
        await _load(uow, principal.tenant_id, broadcast_id)

    use_case = AddBroadcastRecipients(container.unit_of_work())
    added, duplicates, invalid = await use_case.execute(
        principal.tenant_id,
        broadcast_id,
        structured=[(r.phone_number, r.display_name) for r in body.recipients],
        text_blob=body.recipients_text,
    )
    return AddRecipientsResponse(added=added, duplicates=duplicates, invalid=invalid[:50])


@router.post("/preview-contacts", response_model=PreviewContactsResponse)
async def preview_contacts(
    body: PreviewContactsRequest,
    principal: AdminPrincipalDep,
) -> PreviewContactsResponse:
    """Parse a contact blob without saving anything.

    Deliberately campaign-free: the point is to check a pasted list or an
    uploaded file *before* committing to it, so a malformed export is fixed in
    the editor rather than discovered as a short send afterwards.
    """
    parsed = parse_contacts(body.recipients_text)
    # Capped because this feeds a preview table; the count is reported in full
    # so a large file still shows an honest total.
    shown = parsed.recipients[:500]
    return PreviewContactsResponse(
        contacts=[PreviewedContact(phone_number=p, display_name=n) for p, n in shown],
        invalid=parsed.invalid[:100],
        duplicates=parsed.duplicates[:100],
        total_valid=len(parsed.recipients),
        truncated=len(parsed.recipients) > len(shown),
    )


@router.get("/{broadcast_id}/recipients", response_model=RecipientPageResponse)
async def list_recipients(
    broadcast_id: uuid.UUID,
    principal: AdminPrincipalDep,
    container: ContainerDep,
    status: str | None = Query(default=None),
    search: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=25, ge=1, le=100),
) -> RecipientPageResponse:
    async with container.unit_of_work() as uow:
        uow.set_tenant_scope(principal.tenant_id)
        await _load(uow, principal.tenant_id, broadcast_id)
        total = await uow.broadcast_recipients.count_for_broadcast(
            broadcast_id, status=status, search=search
        )
        recipients = await uow.broadcast_recipients.list_for_broadcast(
            broadcast_id,
            status=status,
            search=search,
            limit=page_size,
            offset=(page - 1) * page_size,
        )
    return RecipientPageResponse(
        recipients=[_recipient_response(r) for r in recipients],
        total=total,
        page=page,
        page_size=page_size,
    )


# --- Campaign controls ---


@router.post("/{broadcast_id}/start", response_model=BroadcastResponse)
async def start_broadcast(
    broadcast_id: uuid.UUID,
    principal: AdminPrincipalDep,
    container: ContainerDep,
    background: BackgroundTasks,
) -> BroadcastResponse:
    async with container.unit_of_work() as uow:
        uow.set_tenant_scope(principal.tenant_id)
        broadcast = await _load(uow, principal.tenant_id, broadcast_id)
        if broadcast.total_count == 0:
            raise HTTPException(
                status_code=400, detail="Add at least one contact before starting."
            )
        if broadcast.status == "completed":
            raise HTTPException(
                status_code=400,
                detail="This campaign is completed. Use 'Retry failed' to re-send to "
                "failed contacts.",
            )
        broadcast.start()
        await uow.broadcasts.update(broadcast)
        await uow.commit()
        response = await _decorate(uow, principal.tenant_id, broadcast)

    background.add_task(_run_send, principal.tenant_id, broadcast_id)
    return response


@router.post("/{broadcast_id}/pause", response_model=BroadcastResponse)
async def pause_broadcast(
    broadcast_id: uuid.UUID, principal: AdminPrincipalDep, container: ContainerDep
) -> BroadcastResponse:
    """Halt the sweep. At most one more message can still land — the sweep
    commits one recipient at a time and checks this status before claiming
    the next — because a send already handed to the provider can't be
    recalled."""
    async with container.unit_of_work() as uow:
        uow.set_tenant_scope(principal.tenant_id)
        broadcast = await _load(uow, principal.tenant_id, broadcast_id)
        broadcast.pause()
        await uow.broadcasts.update(broadcast)
        await uow.commit()
        return await _decorate(uow, principal.tenant_id, broadcast)


@router.post("/{broadcast_id}/complete", response_model=BroadcastResponse)
async def complete_broadcast(
    broadcast_id: uuid.UUID, principal: AdminPrincipalDep, container: ContainerDep
) -> BroadcastResponse:
    """Close the campaign out manually, leaving any still-pending contacts unsent."""
    async with container.unit_of_work() as uow:
        uow.set_tenant_scope(principal.tenant_id)
        broadcast = await _load(uow, principal.tenant_id, broadcast_id)
        broadcast.complete()
        await uow.broadcasts.update(broadcast)
        await uow.commit()
        return await _decorate(uow, principal.tenant_id, broadcast)


@router.post("/{broadcast_id}/retry-failed", response_model=BroadcastResponse)
async def retry_failed(
    broadcast_id: uuid.UUID,
    principal: AdminPrincipalDep,
    container: ContainerDep,
    background: BackgroundTasks,
) -> BroadcastResponse:
    """Requeue every failed contact and resume sending."""
    async with container.unit_of_work() as uow:
        uow.set_tenant_scope(principal.tenant_id)
        broadcast = await _load(uow, principal.tenant_id, broadcast_id)
        requeued = await uow.broadcast_recipients.reset_failed(broadcast_id)
        if requeued:
            broadcast.start()
        recipients = await uow.broadcast_recipients.list_for_broadcast(broadcast_id)
        broadcast.recompute_counts(recipients)
        await uow.broadcasts.update(broadcast)
        await uow.commit()
        response = await _decorate(uow, principal.tenant_id, broadcast)

    if requeued:
        background.add_task(_run_send, principal.tenant_id, broadcast_id)
    return response


# --- Chat log + human takeover ---


@router.get(
    "/{broadcast_id}/recipients/{recipient_id}/messages",
    response_model=list[BroadcastMessageResponse],
)
async def recipient_messages(
    broadcast_id: uuid.UUID,
    recipient_id: uuid.UUID,
    principal: AdminPrincipalDep,
    container: ContainerDep,
) -> list[BroadcastMessageResponse]:
    async with container.unit_of_work() as uow:
        uow.set_tenant_scope(principal.tenant_id)
        recipient = await uow.broadcast_recipients.get(principal.tenant_id, recipient_id)
        if recipient is None or recipient.broadcast_id != broadcast_id:
            raise HTTPException(status_code=404, detail="Contact not found")
        if recipient.session_id is None:
            # Nothing was sent yet, so there is no conversation — an empty log,
            # not an error.
            return []
        messages = await uow.chats.list_messages(principal.tenant_id, recipient.session_id)
    return [
        BroadcastMessageResponse(
            id=msg.id,
            role="user" if msg.role == MessageRole.USER else "assistant",
            content=msg.content,
            created_at=msg.created_at,
        )
        for msg in messages
    ]


@router.post(
    "/{broadcast_id}/recipients/{recipient_id}/messages",
    response_model=BroadcastMessageResponse,
    status_code=201,
)
async def send_manual_message(
    broadcast_id: uuid.UUID,
    recipient_id: uuid.UUID,
    body: SendManualMessageRequest,
    principal: AdminPrincipalDep,
    container: ContainerDep,
) -> BroadcastMessageResponse:
    """Human takeover: send as the assistant, bypassing the RAG pipeline.

    The message is persisted to the same session, so the assistant's later
    replies see what the human said and don't contradict it. Sends through
    whichever transport the campaign itself uses — this used to assume Cloud
    API unconditionally, so a personal/QR-linked campaign's composer failed
    with a misleading "channel is gone" on every attempt.
    """
    async with container.unit_of_work() as uow:
        uow.set_tenant_scope(principal.tenant_id)
        recipient = await uow.broadcast_recipients.get(principal.tenant_id, recipient_id)
        if recipient is None or recipient.broadcast_id != broadcast_id:
            raise HTTPException(status_code=404, detail="Contact not found")
        broadcast = await _load(uow, principal.tenant_id, broadcast_id)
        channel = None
        if broadcast.sender_kind == "cloud_api":
            channel = await uow.whatsapp_channels.get(
                principal.tenant_id, broadcast.whatsapp_channel_id
            )
            if channel is None:
                raise HTTPException(
                    status_code=400, detail="This campaign's WhatsApp channel is gone."
                )
        session_id = recipient.session_id

    if session_id is None:
        raise HTTPException(
            status_code=400,
            detail="This contact hasn't been messaged yet — start the campaign first.",
        )

    if broadcast.sender_kind == "cloud_api":
        ok, _sid, error = await container.whatsapp_sender.send(
            account_sid=channel.twilio_account_sid,
            auth_token=channel.twilio_auth_token,
            from_number=channel.phone_number,
            to_number=recipient.phone_number,
            body=body.message,
        )
    else:
        jid = f"{recipient.phone_number.lstrip('+')}@s.whatsapp.net"
        ok, error = await container.whatsapp_bridge.send_text(
            str(broadcast.whatsapp_session_id), jid, body.message
        )
    if not ok:
        raise HTTPException(status_code=502, detail=error)

    message = Message(
        session_id=session_id,
        tenant_id=principal.tenant_id,
        role=MessageRole.ASSISTANT,
        content=body.message,
    )
    async with container.unit_of_work() as uow:
        uow.set_tenant_scope(principal.tenant_id)
        await uow.chats.add_message(message)
        await uow.commit()

    return BroadcastMessageResponse(
        id=message.id,
        role="assistant",
        content=message.content,
        created_at=message.created_at,
    )


# --- Twilio status callback (public, signature-verified — no JWT/API key) ---


@router.post("/status-callback", include_in_schema=False)
async def status_callback(request: Request, container: ContainerDep) -> Response:
    """Advance a recipient through the delivery funnel.

    Twilio gives us only the message SID, so the recipient is resolved first and
    the signature is then verified against *that* recipient's channel token —
    the same trust chain the inbound message webhook uses.
    """
    form = await request.form()
    params = {k: str(v) for k, v in form.items()}
    message_sid = params.get("MessageSid") or params.get("SmsSid") or ""
    raw_status = (params.get("MessageStatus") or params.get("SmsStatus") or "").lower()
    signature = request.headers.get("X-Twilio-Signature", "")

    async with container.unit_of_work() as uow:
        recipient = await uow.broadcast_recipients.get_by_provider_message_id(message_sid)
        if recipient is None:
            # Not one of ours (or a callback for a manual takeover send).
            return Response(status_code=204)
        broadcast = await uow.broadcasts.get_unscoped(recipient.broadcast_id)
        if broadcast is None:
            return Response(status_code=204)
        channel = await uow.whatsapp_channels.get(
            broadcast.tenant_id, broadcast.whatsapp_channel_id
        )

    if channel is None or not verify_twilio_signature(
        _status_callback_url(), params, signature, channel.twilio_auth_token
    ):
        raise HTTPException(status_code=403, detail="Invalid Twilio signature")

    mapped = _TWILIO_STATUS_MAP.get(raw_status)
    if mapped is None:
        return Response(status_code=204)

    async with container.unit_of_work() as uow:
        uow.set_tenant_scope(broadcast.tenant_id)
        current = await uow.broadcast_recipients.get(broadcast.tenant_id, recipient.id)
        if current is None:
            return Response(status_code=204)
        if mapped == "failed":
            current.mark_undeliverable(
                params.get("ErrorMessage") or f"Twilio reported '{raw_status}'."
            )
            changed = True
        else:
            changed = current.advance_to(mapped)  # type: ignore[arg-type]
        if changed:
            await uow.broadcast_recipients.update(current)
            fresh = await uow.broadcasts.get(broadcast.tenant_id, broadcast.id)
            if fresh is not None:
                recipients = await uow.broadcast_recipients.list_for_broadcast(broadcast.id)
                fresh.recompute_counts(recipients)
                await uow.broadcasts.update(fresh)
            await uow.commit()

    return Response(status_code=204)


async def mark_replied(container, session_id: SessionId) -> None:
    """Flip a broadcast recipient to `replied` when they answer.

    Called from the inbound WhatsApp webhook, which knows the session but not
    the campaign. A no-op for sessions that aren't part of a broadcast, so the
    webhook can call it unconditionally.
    """
    async with container.unit_of_work() as uow:
        recipient = await uow.broadcast_recipients.get_by_session(session_id)
        if recipient is None:
            return
        uow.set_tenant_scope(recipient.tenant_id)
        if not recipient.advance_to("replied"):
            return
        await uow.broadcast_recipients.update(recipient)
        broadcast = await uow.broadcasts.get(recipient.tenant_id, recipient.broadcast_id)
        if broadcast is not None:
            recipients = await uow.broadcast_recipients.list_for_broadcast(broadcast.id)
            broadcast.recompute_counts(recipients)
            await uow.broadcasts.update(broadcast)
        await uow.commit()
