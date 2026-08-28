"""Personal WhatsApp linking by QR ("Phone WhatsApp").

Two audiences:

  * The browser (JWT-authenticated) creates a session, polls for the QR, and
    attaches an assistant.
  * The Node bridge (shared-secret) reports connection events and inbound
    messages, and is what turns a message into an assistant reply.

The bridge never sees a tenant. It knows a session id, and the session row is
what maps that back to a tenant and an assistant — the same trust shape the
Twilio webhooks already use.
"""

from __future__ import annotations

import time
import uuid
from datetime import UTC, datetime

import structlog
from fastapi import (
    APIRouter,
    BackgroundTasks,
    File,
    Form,
    Header,
    HTTPException,
    Query,
    UploadFile,
)
from fastapi.responses import Response

from src.application.dtos import AskInput
from src.application.ports.repositories import WhatsAppConversation
from src.application.use_cases.ask_chatbot import AskChatbot
from src.config.container import get_container
from src.config.settings import get_settings
from src.domain.chat.entities import ChatSession, Message, MessageRole
from src.domain.shared.identifiers import ChatbotId, SessionId, TenantId
from src.domain.whatsapp_web.entities import WhatsAppWebSession
from src.infrastructure.llm.resilience import Bulkhead
from src.interfaces.api.deps import AdminPrincipalDep, ContainerDep
from src.interfaces.api.routers.broadcasts import mark_replied
from src.interfaces.api.schemas import (
    AttachAssistantRequest,
    BridgeEventRequest,
    BridgeHistoryMessage,
    BridgeHistoryRequest,
    BridgeHistoryResponse,
    BridgeMediaResponse,
    InboxConversationPageResponse,
    InboxConversationResponse,
    InboxConversationUpdate,
    InboxMessageResponse,
    InboxSendRequest,
    WhatsAppWebOptionsResponse,
    WhatsAppWebSessionResponse,
)

router = APIRouter(prefix="/whatsapp-web", tags=["whatsapp-web"])

log = structlog.get_logger(__name__)

# A linked personal account is deliberately inbound-only: it answers people who
# message it. Bulk outbound belongs on the official Twilio path, where the
# recipient consented — and it is what gets personal numbers banned.
_MAX_SESSIONS_PER_TENANT = 5

# Ceiling on the back-fill when an assistant is attached. A full history import
# can leave thousands of threads, and re-pointing them is a single UPDATE ...
# IN (...) — bounded so the request cannot degrade into an unbounded statement.
# Threads past the cap are the coldest ones, and they self-heal: the answer path
# re-points a thread the first time a message arrives on it.
_MAX_THREADS_TO_REPOINT = 500

# Matches the bridge's own inbound cap (BRIDGE_MAX_MEDIA_MB, default 16) so an
# operator never uploads a file the outbound send is going to reject anyway.
_MAX_ATTACHMENT_BYTES = 16 * 1024 * 1024

# Caps how many auto-replies are generated at once in this process. Lazily
# built so the semaphore binds to the event loop actually serving requests
# (a module-level `asyncio.Semaphore` binds to whichever loop imported it,
# which is not the same one under Uvicorn's reloader or in tests).
_reply_bulkhead: Bulkhead | None = None


def _reply_gate() -> Bulkhead:
    global _reply_bulkhead
    if _reply_bulkhead is None:
        _reply_bulkhead = Bulkhead(get_settings().whatsapp_reply_max_concurrency)
    return _reply_bulkhead


# How old an inbound message may be and still get an automatic answer.
# Generous on purpose: the failure being guarded against is replying to a
# days-old thread, while the failure this replaces — never replying at all —
# was caused by being far too strict. A reply WhatsApp held for an hour while
# the bridge slept is still a reply the contact is waiting on.
_MAX_REPLY_AGE_SECONDS = 12 * 60 * 60


def _too_stale_to_answer(body: BridgeEventRequest) -> bool:
    """Is this message old enough that answering would be talking to the past?

    A missing timestamp (`0`) means the bridge did not report one — an older
    sidecar, or a message shape Baileys did not stamp. That is treated as
    answerable rather than stale: staying silent is the failure mode operators
    actually hit, and a message we just received is almost always current.
    """
    if body.timestamp <= 0:
        return False
    return (int(time.time()) - body.timestamp) > _MAX_REPLY_AGE_SECONDS


def _media_kind_for(mime_type: str) -> str:
    """Classify an outbound attachment the same way inbound media already is
    (see whatsapp-bridge/src/media.js MEDIA_KINDS) — the inbox filters and
    renders on this value regardless of which direction it came from."""
    if mime_type.startswith("image/"):
        return "image"
    if mime_type.startswith("video/"):
        return "video"
    if mime_type.startswith("audio/"):
        return "audio"
    return "document"


def _to_response(ws: WhatsAppWebSession, chatbot_name: str = "") -> WhatsAppWebSessionResponse:
    fresh = ws.qr_is_fresh()
    return WhatsAppWebSessionResponse(
        id=ws.id,
        chatbot_id=ws.chatbot_id,
        chatbot_name=chatbot_name,
        status=ws.status,  # type: ignore[arg-type]
        phone_number=ws.phone_number,
        display_name=ws.display_name,
        # Never serve a stale QR: it stopped working the moment it expired, and
        # showing it just makes scanning fail silently.
        qr_data_url=ws.qr_data_url if fresh else "",
        qr_seconds_remaining=ws.qr_seconds_remaining() if fresh else 0,
        last_error=ws.last_error,
        health=ws.health(),
        linked_at=ws.linked_at,
        created_at=ws.created_at,
    )


async def _named(uow, tenant_id: TenantId, ws: WhatsAppWebSession) -> WhatsAppWebSessionResponse:
    name = ""
    if ws.chatbot_id:
        bot = await uow.chatbots.get(tenant_id, ws.chatbot_id)
        name = bot.name if bot else ""
    return _to_response(ws, name)


# --- Browser-facing ---


@router.get("/options", response_model=WhatsAppWebOptionsResponse)
async def options(
    principal: AdminPrincipalDep, container: ContainerDep
) -> WhatsAppWebOptionsResponse:
    if not container.whatsapp_bridge.enabled:
        return WhatsAppWebOptionsResponse(
            enabled=False,
            bridge_healthy=False,
            message="Personal WhatsApp linking isn't configured on this server "
            "(needs BRIDGE_TOKEN and the whatsapp-bridge service).",
        )
    healthy, error = await container.whatsapp_bridge.health()
    return WhatsAppWebOptionsResponse(
        enabled=True,
        bridge_healthy=healthy,
        message="" if healthy else error,
    )


@router.get("/sessions", response_model=list[WhatsAppWebSessionResponse])
async def list_sessions(
    principal: AdminPrincipalDep, container: ContainerDep
) -> list[WhatsAppWebSessionResponse]:
    async with container.unit_of_work() as uow:
        uow.set_tenant_scope(principal.tenant_id)
        sessions = await uow.whatsapp_web_sessions.list_for_tenant(principal.tenant_id)
        return [await _named(uow, principal.tenant_id, s) for s in sessions]


@router.post("/sessions", response_model=WhatsAppWebSessionResponse, status_code=201)
async def create_session(
    principal: AdminPrincipalDep, container: ContainerDep
) -> WhatsAppWebSessionResponse:
    """Create a session and ask the bridge to begin pairing.

    The QR is not in this response — Baileys mints it a moment later and reports
    it as a bridge event. The client polls GET /sessions/{id} for it, which is
    also how it picks up the ~20s QR rotation.
    """
    if not container.whatsapp_bridge.enabled:
        raise HTTPException(
            status_code=400,
            detail="Personal WhatsApp linking isn't configured on this server.",
        )

    async with container.unit_of_work() as uow:
        uow.set_tenant_scope(principal.tenant_id)
        existing = await uow.whatsapp_web_sessions.list_for_tenant(principal.tenant_id)
        if len(existing) >= _MAX_SESSIONS_PER_TENANT:
            raise HTTPException(
                status_code=400,
                detail=f"At most {_MAX_SESSIONS_PER_TENANT} linked WhatsApp numbers "
                "per workspace. Remove one first.",
            )
        ws = WhatsAppWebSession(tenant_id=principal.tenant_id)
        await uow.whatsapp_web_sessions.add(ws)
        await uow.commit()

    ok, error = await container.whatsapp_bridge.start_session(str(ws.id))
    if not ok:
        ws.mark_failed(error)
        async with container.unit_of_work() as uow:
            uow.set_tenant_scope(principal.tenant_id)
            await uow.whatsapp_web_sessions.update(ws)
            await uow.commit()
    return _to_response(ws)


@router.get("/sessions/{session_id}", response_model=WhatsAppWebSessionResponse)
async def get_session(
    session_id: uuid.UUID, principal: AdminPrincipalDep, container: ContainerDep
) -> WhatsAppWebSessionResponse:
    """Polled by the QR modal — carries the current QR, its countdown, and the
    status that tells the modal when to close."""
    async with container.unit_of_work() as uow:
        uow.set_tenant_scope(principal.tenant_id)
        ws = await uow.whatsapp_web_sessions.get(principal.tenant_id, session_id)
        if ws is None:
            raise HTTPException(status_code=404, detail="Session not found")
        return await _named(uow, principal.tenant_id, ws)


@router.post("/sessions/{session_id}/refresh", response_model=WhatsAppWebSessionResponse)
async def refresh_qr(
    session_id: uuid.UUID, principal: AdminPrincipalDep, container: ContainerDep
) -> WhatsAppWebSessionResponse:
    """Restart pairing after the QR window lapsed."""
    async with container.unit_of_work() as uow:
        uow.set_tenant_scope(principal.tenant_id)
        ws = await uow.whatsapp_web_sessions.get(principal.tenant_id, session_id)
        if ws is None:
            raise HTTPException(status_code=404, detail="Session not found")
        if ws.status == "linked":
            raise HTTPException(status_code=400, detail="This number is already linked.")

    ok, error = await container.whatsapp_bridge.start_session(str(session_id))
    if not ok:
        raise HTTPException(status_code=502, detail=error)
    return _to_response(ws)


@router.patch("/sessions/{session_id}/assistant", response_model=WhatsAppWebSessionResponse)
async def attach_assistant(
    session_id: uuid.UUID,
    body: AttachAssistantRequest,
    principal: AdminPrincipalDep,
    container: ContainerDep,
) -> WhatsAppWebSessionResponse:
    """Choose which assistant answers this number. Null detaches it — messages
    still arrive and are stored, but nothing replies.

    Threads that already exist are re-pointed at the new assistant. They were
    stamped with whatever was attached when their first message landed — usually
    nothing, because linking comes before choosing — and the answer path reads
    the thread, so without the back-fill picking an assistant would only ever
    affect conversations that started later.
    """
    async with container.unit_of_work() as uow:
        uow.set_tenant_scope(principal.tenant_id)
        ws = await uow.whatsapp_web_sessions.get(principal.tenant_id, session_id)
        if ws is None:
            raise HTTPException(status_code=404, detail="Session not found")
        chatbot_id = ChatbotId(body.chatbot_id) if body.chatbot_id else None
        if chatbot_id is not None:
            bot = await uow.chatbots.get(principal.tenant_id, chatbot_id)
            if bot is None:
                raise HTTPException(status_code=404, detail="Chatbot not found")
        ws.attach_chatbot(chatbot_id)
        await uow.whatsapp_web_sessions.update(ws)

        threads = await uow.whatsapp_conversations.list_for_owner(
            principal.tenant_id, session_id, limit=_MAX_THREADS_TO_REPOINT
        )
        moved = await uow.chats.assign_chatbot(
            principal.tenant_id, [t.session_id for t in threads], chatbot_id
        )
        await uow.commit()
        log.info(
            "whatsapp.assistant_attached",
            session_id=str(session_id),
            chatbot_id=str(chatbot_id) if chatbot_id else None,
            threads_repointed=moved,
        )
        return await _named(uow, principal.tenant_id, ws)


@router.delete("/sessions/{session_id}", status_code=204)
async def unlink(
    session_id: uuid.UUID, principal: AdminPrincipalDep, container: ContainerDep
) -> None:
    """Unlink at WhatsApp, then delete the row (which cascades the stored keys)."""
    async with container.unit_of_work() as uow:
        uow.set_tenant_scope(principal.tenant_id)
        ws = await uow.whatsapp_web_sessions.get(principal.tenant_id, session_id)
        if ws is None:
            return

    # Ask WhatsApp to drop the device first — after the row is gone, the bridge
    # can no longer resolve the session and the phone would keep showing a dead
    # linked device.
    await container.whatsapp_bridge.logout_session(str(session_id))

    async with container.unit_of_work() as uow:
        uow.set_tenant_scope(principal.tenant_id)
        await uow.whatsapp_web_sessions.delete(principal.tenant_id, session_id)
        await uow.commit()


# --- Inbox (browser-facing) ---


def _conversation_response(c: WhatsAppConversation) -> InboxConversationResponse:
    return InboxConversationResponse(
        id=c.id,
        phone_number=c.phone_number,
        display_name=c.display_name,
        last_message_at=c.last_message_at,
        last_message_preview=c.last_message_preview,
        unread_count=c.unread_count,
        has_attachment=c.has_attachment,
        auto_reply=c.auto_reply,
    )


def _author_of(msg: Message) -> str:
    """Who wrote this message, from the provider tag already on the row.

    "whatsapp:operator" is a reply typed in the inbox, "whatsapp:device" one
    typed on the phone itself, and anything else on an outgoing message is a
    generated answer — those are tagged with the LLM provider that produced
    them ("groq", "gemini", …), which is exactly the set we want to call
    "assistant".
    """
    if msg.role == MessageRole.USER:
        return "contact"
    if msg.provider == "whatsapp:operator":
        return "operator"
    if msg.provider == "whatsapp:device":
        return "device"
    return "assistant"


async def _owned_conversation(
    uow, tenant_id: TenantId, conversation_id: uuid.UUID
) -> WhatsAppConversation:
    conversation = await uow.whatsapp_conversations.get_by_id(tenant_id, conversation_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return conversation


@router.get("/sessions/{session_id}/conversations", response_model=InboxConversationPageResponse)
async def list_conversations(
    session_id: uuid.UUID,
    principal: AdminPrincipalDep,
    container: ContainerDep,
    search: str = Query("", max_length=120),
    has_attachment: bool | None = None,
    unread_only: bool = False,
    auto_reply: bool | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(30, ge=1, le=100),
) -> InboxConversationPageResponse:
    """The inbox thread list for one linked number."""
    async with container.unit_of_work() as uow:
        uow.set_tenant_scope(principal.tenant_id)
        # Confirms the session belongs to this tenant before it is used as the
        # owner id — `whatsapp_conversations` is keyed by a polymorphic owner,
        # so an unchecked id would read another tenant's threads.
        ws = await uow.whatsapp_web_sessions.get(principal.tenant_id, session_id)
        if ws is None:
            raise HTTPException(status_code=404, detail="Session not found")

        filters = {
            "search": search.strip(),
            "has_attachment": has_attachment,
            "unread_only": unread_only,
            "auto_reply": auto_reply,
        }
        total = await uow.whatsapp_conversations.count_for_owner(
            principal.tenant_id, session_id, **filters
        )
        conversations = await uow.whatsapp_conversations.list_for_owner(
            principal.tenant_id,
            session_id,
            **filters,
            limit=page_size,
            offset=(page - 1) * page_size,
        )
    return InboxConversationPageResponse(
        conversations=[_conversation_response(c) for c in conversations],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/conversations/{conversation_id}/messages", response_model=list[InboxMessageResponse])
async def list_conversation_messages(
    conversation_id: uuid.UUID,
    principal: AdminPrincipalDep,
    container: ContainerDep,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> list[InboxMessageResponse]:
    async with container.unit_of_work() as uow:
        uow.set_tenant_scope(principal.tenant_id)
        conversation = await _owned_conversation(uow, principal.tenant_id, conversation_id)
        messages = await uow.chats.list_messages(
            principal.tenant_id, conversation.session_id, limit=limit, offset=offset
        )
    return [
        InboxMessageResponse(
            id=msg.id,
            direction="in" if msg.role == MessageRole.USER else "out",
            author=_author_of(msg),
            content=msg.content,
            created_at=msg.created_at,
            media_kind=msg.media_kind or "",
            media_mime_type=msg.media_mime_type or "",
            media_filename=msg.media_filename or "",
            media_size_bytes=msg.media_size_bytes or 0,
            # An attachment WhatsApp delivered but we could not store has the
            # metadata and no key; the UI shows it as unavailable rather than
            # offering a download that would 404.
            media_available=bool(msg.media_storage_key),
        )
        for msg in messages
    ]


@router.post(
    "/conversations/{conversation_id}/messages",
    response_model=InboxMessageResponse,
    status_code=201,
)
async def send_conversation_message(
    conversation_id: uuid.UUID,
    body: InboxSendRequest,
    principal: AdminPrincipalDep,
    container: ContainerDep,
) -> InboxMessageResponse:
    """Reply by hand, as the operator.

    Does not reuse the campaign takeover endpoint: that one resolves a Twilio
    channel unconditionally and rejects anything sent from a QR-linked number.
    """
    async with container.unit_of_work() as uow:
        uow.set_tenant_scope(principal.tenant_id)
        conversation = await _owned_conversation(uow, principal.tenant_id, conversation_id)
        ws = await uow.whatsapp_web_sessions.get(
            principal.tenant_id, conversation.whatsapp_channel_id
        )
        if ws is None or ws.status != "linked":
            raise HTTPException(
                status_code=400, detail="This WhatsApp number is not currently linked."
            )

    jid = f"{conversation.phone_number.lstrip('+')}@s.whatsapp.net"
    ok, error = await container.whatsapp_bridge.send_text(
        str(conversation.whatsapp_channel_id), jid, body.message
    )
    if not ok:
        raise HTTPException(status_code=502, detail=error)

    message = Message(
        session_id=conversation.session_id,
        tenant_id=principal.tenant_id,
        role=MessageRole.ASSISTANT,
        content=body.message,
        # Marks this as a human reply rather than a generated answer.
        provider="whatsapp:operator",
    )
    async with container.unit_of_work() as uow:
        uow.set_tenant_scope(principal.tenant_id)
        await uow.chats.add_message(message)
        conversation.note_message(preview=body.message, has_media=False, inbound=False)
        await uow.whatsapp_conversations.update(conversation)
        await uow.commit()

    return InboxMessageResponse(
        id=message.id,
        direction="out",
        author="operator",
        content=message.content,
        created_at=message.created_at,
    )


@router.post(
    "/conversations/{conversation_id}/attachments",
    response_model=InboxMessageResponse,
    status_code=201,
)
async def send_conversation_attachment(
    conversation_id: uuid.UUID,
    principal: AdminPrincipalDep,
    container: ContainerDep,
    file: UploadFile = File(...),
    caption: str = Form(""),
) -> InboxMessageResponse:
    """Send a file as the operator, with an optional caption.

    A separate endpoint from `send_conversation_message` rather than an
    optional field there: that one is plain JSON, and a file needs multipart.
    Personal/QR-linked numbers only — Twilio's WhatsApp API needs a publicly
    fetchable URL for media, which this deployment's storage doesn't issue.
    """
    payload = await file.read()
    if not payload:
        raise HTTPException(status_code=400, detail="Empty upload")
    if len(payload) > _MAX_ATTACHMENT_BYTES:
        raise HTTPException(
            status_code=400,
            detail=f"Attachments are limited to {_MAX_ATTACHMENT_BYTES // (1024 * 1024)}MB.",
        )

    async with container.unit_of_work() as uow:
        uow.set_tenant_scope(principal.tenant_id)
        conversation = await _owned_conversation(uow, principal.tenant_id, conversation_id)
        ws = await uow.whatsapp_web_sessions.get(
            principal.tenant_id, conversation.whatsapp_channel_id
        )
        if ws is None or ws.status != "linked":
            raise HTTPException(
                status_code=400, detail="This WhatsApp number is not currently linked."
            )

    mime_type = file.content_type or "application/octet-stream"
    media_kind = _media_kind_for(mime_type)
    filename = file.filename or media_kind
    # Same storage backend and proxied-download convention as inbound media
    # (see conversation_media below) — never a public URL.
    storage_key = f"whatsapp/out/{conversation.whatsapp_channel_id}/{uuid.uuid4().hex}"
    await container.storage.put_bytes(storage_key, payload, mime_type)

    jid = f"{conversation.phone_number.lstrip('+')}@s.whatsapp.net"
    ok, error = await container.whatsapp_bridge.send_media(
        str(conversation.whatsapp_channel_id),
        jid,
        payload,
        media_kind=media_kind,
        mime_type=mime_type,
        filename=filename,
        caption=caption,
    )
    if not ok:
        raise HTTPException(status_code=502, detail=error)

    message = Message(
        session_id=conversation.session_id,
        tenant_id=principal.tenant_id,
        role=MessageRole.ASSISTANT,
        content=caption,
        provider="whatsapp:operator",
        media_kind=media_kind,
        media_mime_type=mime_type,
        media_filename=filename,
        media_storage_key=storage_key,
        media_size_bytes=len(payload),
    )
    async with container.unit_of_work() as uow:
        uow.set_tenant_scope(principal.tenant_id)
        await uow.chats.add_message(message)
        conversation.note_message(preview=caption or media_kind, has_media=True, inbound=False)
        await uow.whatsapp_conversations.update(conversation)
        await uow.commit()

    return InboxMessageResponse(
        id=message.id,
        direction="out",
        author="operator",
        content=message.content,
        created_at=message.created_at,
        media_kind=media_kind,
        media_mime_type=mime_type,
        media_filename=filename,
        media_size_bytes=len(payload),
        media_available=True,
    )


@router.patch("/conversations/{conversation_id}", response_model=InboxConversationResponse)
async def update_conversation(
    conversation_id: uuid.UUID,
    body: InboxConversationUpdate,
    principal: AdminPrincipalDep,
    container: ContainerDep,
) -> InboxConversationResponse:
    """Take a conversation over from the assistant, or mark it read."""
    async with container.unit_of_work() as uow:
        uow.set_tenant_scope(principal.tenant_id)
        conversation = await _owned_conversation(uow, principal.tenant_id, conversation_id)
        if body.auto_reply is not None:
            conversation.set_auto_reply(body.auto_reply)
        if body.mark_read:
            conversation.mark_read()
        await uow.whatsapp_conversations.update(conversation)
        await uow.commit()
    return _conversation_response(conversation)


@router.get("/conversations/{conversation_id}/media/{message_id}")
async def conversation_media(
    conversation_id: uuid.UUID,
    message_id: uuid.UUID,
    principal: AdminPrincipalDep,
    container: ContainerDep,
) -> Response:
    """Stream one attachment.

    Proxied rather than handed out as a storage URL: the bytes are a tenant's
    customer conversation, and a presigned link would be shareable by anyone who
    saw it.
    """
    async with container.unit_of_work() as uow:
        uow.set_tenant_scope(principal.tenant_id)
        conversation = await _owned_conversation(uow, principal.tenant_id, conversation_id)
        messages = await uow.chats.list_messages(principal.tenant_id, conversation.session_id)

    match = next((m for m in messages if m.id == message_id and m.media_storage_key), None)
    if match is None:
        raise HTTPException(status_code=404, detail="Attachment not found")

    try:
        payload = await container.storage.get_bytes(match.media_storage_key)
    except Exception as exc:  # noqa: BLE001 — R2 raises NoSuchKey, disk raises OSError
        # Expected on this deployment: with R2 unset, attachments live on
        # Render's ephemeral disk and do not survive a redeploy.
        log.warning("whatsapp.media.missing", key=match.media_storage_key, error=str(exc))
        raise HTTPException(
            status_code=404, detail="This attachment is no longer stored."
        ) from exc
    headers = {}
    if match.media_filename:
        headers["Content-Disposition"] = f'inline; filename="{match.media_filename}"'
    return Response(
        content=payload,
        media_type=match.media_mime_type or "application/octet-stream",
        headers=headers,
    )


# --- Bridge-facing (shared secret, no JWT) ---


async def _ensure_conversation(
    uow,
    tenant_id: TenantId,
    chatbot_id: ChatbotId | None,
    session_id: uuid.UUID,
    phone: str,
    display_name: str,
) -> WhatsAppConversation:
    """Find or create the thread for one contact.

    Deliberately does not require an assistant: a number with nothing attached
    still needs somewhere to put its messages, or the inbox is empty for exactly
    the case where someone is trying to read what came in.
    """
    conversation = await uow.whatsapp_conversations.get(session_id, phone)
    if conversation is not None:
        if display_name and not conversation.display_name:
            conversation.display_name = display_name
        return conversation

    chat = ChatSession(
        tenant_id=tenant_id,
        # A session must belong to a chatbot; when none is attached yet, the
        # thread is still recorded and simply goes unanswered.
        chatbot_id=chatbot_id,
        title=display_name or phone,
    )
    await uow.chats.add_session(chat)
    conversation = WhatsAppConversation(
        whatsapp_channel_id=session_id,
        phone_number=phone,
        session_id=chat.id,
        tenant_id=tenant_id,
        display_name=display_name,
    )
    await uow.whatsapp_conversations.add(conversation)
    return conversation


async def _store_message(
    uow,
    tenant_id: TenantId,
    conversation: WhatsAppConversation,
    body: BridgeEventRequest,
) -> bool:
    """Persist one WhatsApp message. Returns False if it was a redelivery.

    The socket replays messages after a reconnect, so without the provider-id
    check a flaky connection would duplicate a whole thread.
    """
    if body.message_id and await uow.chats.message_exists(
        tenant_id, conversation.session_id, body.message_id
    ):
        return False

    inbound = body.direction == "in"
    await uow.chats.add_message(
        Message(
            session_id=conversation.session_id,
            tenant_id=tenant_id,
            role=MessageRole.USER if inbound else MessageRole.ASSISTANT,
            content=body.text,
            # Distinguishes a human reply typed on the phone from an assistant
            # answer, which otherwise share the "assistant" role.
            provider=None if inbound else "whatsapp:device",
            media_kind=body.media_kind or None,
            media_mime_type=body.media_mime_type or None,
            media_filename=body.media_filename or None,
            media_storage_key=body.media_storage_key or None,
            media_size_bytes=body.media_size_bytes or None,
            provider_message_id=body.message_id or None,
        )
    )
    conversation.note_message(
        preview=body.preview or body.text,
        has_media=bool(body.media_kind),
        inbound=inbound,
    )
    await uow.whatsapp_conversations.update(conversation)
    return True


async def _reply_to_message(
    tenant_id: TenantId,
    chat_session_id: SessionId,
    session_id: uuid.UUID,
    chatbot_id: ChatbotId,
    jid: str,
    phone: str,
    text: str,
) -> None:
    """Run the message through the assistant and send the answer back.

    A background task, not inline: retrieval plus generation takes seconds, and
    the bridge's event POST should return immediately so its socket handler
    isn't blocked behind the RAG pipeline. The inbound message is already
    stored by the caller — hence `persist_user_message=False`, which stops it
    being written a second time.

    `chatbot_id` is the assistant currently attached to the *number*, passed
    explicitly rather than left to the chat session's own column: the session
    was stamped when the thread began and does not follow later changes.

    Every outcome is logged. This runs after the response has gone back to the
    bridge, so a silent failure here is invisible from both ends — which is
    exactly how "I attached an agent and nothing ever replies" stays a mystery.

    Concurrency is capped by `_reply_gate`. Inbound WhatsApp traffic is bursty
    by nature — a campaign to hundreds of contacts produces a cluster of
    replies within seconds, across every linked account at once — and each
    reply is a full RAG pipeline holding a database connection while it calls
    out to a provider. Unbounded, a burst exhausts the connection pool and the
    provider quota simultaneously, so every conversation fails instead of all
    of them simply taking a little longer. Waiting here is backpressure, not
    loss: the message is already stored, and the queue drains in order.
    """
    container = get_container()
    async with _reply_gate()():
        await _generate_and_send_reply(
            container, tenant_id, chat_session_id, session_id, chatbot_id, jid, phone, text
        )


async def _generate_and_send_reply(
    container,
    tenant_id: TenantId,
    chat_session_id: SessionId,
    session_id: uuid.UUID,
    chatbot_id: ChatbotId,
    jid: str,
    phone: str,
    text: str,
) -> None:
    """The reply pipeline itself, run under the concurrency gate above."""
    use_case = AskChatbot(container.unit_of_work(), container.embedder, container.llm)
    started = time.perf_counter()
    # AskChatbot persists a successful answer itself; a fallback bypasses it and
    # has to be written here, or the inbox shows the contact's message with no
    # sign of what they were actually sent back.
    persist_answer = False
    try:
        result = await use_case.execute(
            tenant_id,
            chat_session_id,
            AskInput(message=text, persist_user_message=False, chatbot_id=chatbot_id),
        )
        answer = result.answer
        log.info(
            "whatsapp.reply.generated",
            session_id=str(session_id),
            chatbot_id=str(chatbot_id),
            citations=len(result.citations),
            provider=result.provider,
            latency_ms=int((time.perf_counter() - started) * 1000),
        )
    except Exception as exc:  # noqa: BLE001 — always answer, even on a pipeline failure
        log.exception(
            "whatsapp.reply.failed",
            session_id=str(session_id),
            chatbot_id=str(chatbot_id),
            error=f"{type(exc).__name__}: {exc}",
        )
        answer = "Sorry, something went wrong on our end. Please try again shortly."
        persist_answer = True

    sent, error = await container.whatsapp_bridge.send_text(str(session_id), jid, answer)
    if not sent:
        # The answer exists but never reached the contact. Advancing the thread
        # anyway would show the operator a message that was never delivered, so
        # the thread is left alone and the failure is logged loudly.
        log.error("whatsapp.reply.send_failed", session_id=str(session_id), error=error)
        return

    # Keep the thread list in step with what the contact actually sees.
    async with container.unit_of_work() as uow:
        uow.set_tenant_scope(tenant_id)
        if persist_answer:
            await uow.chats.add_message(
                Message(
                    session_id=chat_session_id,
                    tenant_id=tenant_id,
                    role=MessageRole.ASSISTANT,
                    content=answer,
                    provider="whatsapp:assistant",
                )
            )
        conversation = await uow.whatsapp_conversations.get(session_id, phone)
        if conversation is not None:
            conversation.note_message(preview=answer, has_media=False, inbound=False)
            await uow.whatsapp_conversations.update(conversation)
        await uow.commit()


@router.post("/bridge-media", include_in_schema=False, response_model=BridgeMediaResponse)
async def bridge_media(
    container: ContainerDep,
    session_id: str = Form(...),
    message_id: str = Form(...),
    media_kind: str = Form(""),
    file: UploadFile = File(...),
    x_bridge_token: str = Header(default=""),
) -> BridgeMediaResponse:
    """Take an attachment's bytes from the bridge and put them in object storage.

    Multipart rather than base64 on the event: the bridge's JSON body limit is
    1mb and real attachments are larger. Storing here rather than in the bridge
    keeps one storage backend (R2, or local disk in development) and one set of
    credentials, on the side that already has them.
    """
    settings = get_settings()
    if not settings.bridge_token or x_bridge_token != settings.bridge_token:
        raise HTTPException(status_code=403, detail="Invalid bridge token")

    payload = await file.read()
    if not payload:
        raise HTTPException(status_code=400, detail="Empty upload")

    # Keyed by session and WhatsApp message id: stable, collision-free, and it
    # makes orphaned media for a deleted session easy to find.
    safe_message_id = "".join(c for c in message_id if c.isalnum() or c in "-_")[:64]
    key = f"whatsapp/{session_id}/{safe_message_id or uuid.uuid4().hex}"
    await container.storage.put_bytes(
        key, payload, file.content_type or "application/octet-stream"
    )
    log.info("whatsapp.media.stored", session_id=session_id, kind=media_kind, bytes=len(payload))
    return BridgeMediaResponse(storage_key=key)


@router.post(
    "/bridge-history", include_in_schema=False, response_model=BridgeHistoryResponse
)
async def bridge_history(
    body: BridgeHistoryRequest,
    container: ContainerDep,
    x_bridge_token: str = Header(default=""),
) -> BridgeHistoryResponse:
    """Import a chunk of the history WhatsApp pushed after linking.

    Idempotent by WhatsApp message id, because the phone re-sends overlapping
    chunks and a re-link starts the whole sync again.

    Nothing here answers anybody: imported conversations are historical, and
    running an archive through the assistant would message people about
    conversations they finished months ago.
    """
    settings = get_settings()
    if not settings.bridge_token or x_bridge_token != settings.bridge_token:
        raise HTTPException(status_code=403, detail="Invalid bridge token")

    async with container.unit_of_work() as uow:
        ws = await uow.whatsapp_web_sessions.get_unscoped(body.session_id)
    if ws is None:
        return BridgeHistoryResponse(
            contacts_imported=0, messages_imported=0, skipped_duplicates=0
        )

    contacts_imported = 0
    messages_imported = 0
    skipped = 0

    async with container.unit_of_work() as uow:
        uow.set_tenant_scope(ws.tenant_id)

        # Contacts first: a name makes the thread findable even when the import
        # brings no messages for it, which is the whole point of "search for the
        # printer and get their number".
        for contact in body.contacts:
            conversation = await _ensure_conversation(
                uow, ws.tenant_id, ws.chatbot_id, ws.id, contact.phone, contact.name
            )
            if contact.name and conversation.display_name != contact.name:
                conversation.display_name = contact.name
            await uow.whatsapp_conversations.update(conversation)
            contacts_imported += 1

        # Messages grouped by contact so each thread costs one dedupe query
        # rather than one per message.
        by_phone: dict[str, list[BridgeHistoryMessage]] = {}
        for msg in body.messages:
            by_phone.setdefault(msg.phone, []).append(msg)

        for phone, items in by_phone.items():
            named = next((i.pushname for i in items if i.pushname), "")
            conversation = await _ensure_conversation(
                uow, ws.tenant_id, ws.chatbot_id, ws.id, phone, named
            )
            already = await uow.chats.existing_provider_ids(
                ws.tenant_id,
                conversation.session_id,
                [i.message_id for i in items if i.message_id],
            )

            fresh: list[Message] = []
            for item in items:
                if item.message_id and item.message_id in already:
                    skipped += 1
                    continue
                inbound = item.direction == "in"
                fresh.append(
                    Message(
                        session_id=conversation.session_id,
                        tenant_id=ws.tenant_id,
                        role=MessageRole.USER if inbound else MessageRole.ASSISTANT,
                        content=item.text,
                        provider=None if inbound else "whatsapp:device",
                        created_at=item.timestamp or datetime.now(UTC),
                        media_kind=item.media_kind or None,
                        media_mime_type=item.media_mime_type or None,
                        media_filename=item.media_filename or None,
                        # Deliberately no storage key: WhatsApp expires media
                        # server-side, so historical files are metadata only.
                        media_size_bytes=item.media_size_bytes or None,
                        provider_message_id=item.message_id or None,
                    )
                )

            if fresh:
                await uow.chats.add_messages(fresh)
                messages_imported += len(fresh)
                # Recomputed from the actual newest message rather than "now",
                # so an imported thread sorts by when it really happened.
                newest = max(fresh, key=lambda msg: msg.created_at)
                if (
                    conversation.last_message_at is None
                    or newest.created_at > conversation.last_message_at
                ):
                    conversation.last_message_at = newest.created_at
                    conversation.last_message_preview = (
                        newest.content or newest.media_kind or ""
                    )[:300]
                if any(msg.media_kind for msg in fresh):
                    conversation.has_attachment = True
            await uow.whatsapp_conversations.update(conversation)

        await uow.commit()

    log.info(
        "whatsapp.history.imported",
        session_id=str(body.session_id),
        contacts=contacts_imported,
        messages=messages_imported,
        duplicates=skipped,
    )
    return BridgeHistoryResponse(
        contacts_imported=contacts_imported,
        messages_imported=messages_imported,
        skipped_duplicates=skipped,
    )


@router.post("/bridge-events", include_in_schema=False)
async def bridge_events(
    body: BridgeEventRequest,
    container: ContainerDep,
    background: BackgroundTasks,
    x_bridge_token: str = Header(default=""),
) -> dict[str, str]:
    settings = get_settings()
    if not settings.bridge_token or x_bridge_token != settings.bridge_token:
        raise HTTPException(status_code=403, detail="Invalid bridge token")

    async with container.unit_of_work() as uow:
        ws = await uow.whatsapp_web_sessions.get_unscoped(body.session_id)
    if ws is None:
        # The row was deleted while the socket was still alive. Tell the bridge
        # so it can stop rather than keep reporting into the void.
        return {"status": "unknown_session"}

    if body.event == "message":
        phone = body.from_ or body.phone_number
        # A message just arrived over the socket, which is proof the link is
        # alive. Statuses drift out of step with reality — a transient drop
        # writes "disconnected", and if the reconnect's "linked" event misses
        # the API (a sleeping free-tier instance answers nothing) the row stays
        # that way forever. `is_live()` then refuses to answer anything, which
        # is how a working number quietly stops replying while its inbox keeps
        # filling up.
        ws.observe_traffic()

        # Store first, decide second. Every early return below used to happen
        # BEFORE anything was written, so a number with no assistant attached —
        # or a conversation a human had taken over — recorded nothing at all and
        # the inbox had nothing to show.
        async with container.unit_of_work() as uow:
            uow.set_tenant_scope(ws.tenant_id)
            await uow.whatsapp_web_sessions.update(ws)
            conversation = await _ensure_conversation(
                uow, ws.tenant_id, ws.chatbot_id, ws.id, phone, body.pushname
            )
            stored = await _store_message(uow, ws.tenant_id, conversation, body)
            # Threads outlive the assistant they were opened under, so a thread
            # created before (or under a different) assistant is corrected here
            # as well as on attach. Keeps history and analytics attributing the
            # conversation to whoever is actually answering it.
            if ws.chatbot_id is not None:
                await uow.chats.assign_chatbot(
                    ws.tenant_id, [conversation.session_id], ws.chatbot_id
                )
            # The number itself may have nothing attached (personal accounts
            # attach an assistant separately from picking one for a campaign),
            # while the thread's own session already carries the assistant the
            # campaign was sent with (see SendBroadcast._ensure_conversation).
            # Falling back to that is what makes a campaign's replies actually
            # get answered without also requiring the operator to attach the
            # same assistant to the number a second time.
            chat_session_id = conversation.session_id
            session = await uow.chats.get_session(ws.tenant_id, chat_session_id)
            await uow.commit()
            auto_reply = conversation.auto_reply
            effective_chatbot_id = ws.chatbot_id or (session.chatbot_id if session else None)

        if not stored:
            # A redelivery after a socket reconnect; already in the thread.
            return {"status": "duplicate"}

        if body.direction == "out":
            # Typed by the operator on the phone. Recorded so the inbox matches
            # WhatsApp, never answered — that would be talking to ourselves.
            return {"status": "stored"}

        # A reply on a campaign thread advances that recipient's funnel. The
        # Twilio path has always done this; the personal path never did, so
        # personal-sender campaigns reported zero replies. Runs for synced
        # messages too: a reply that reached us late is still a reply, and the
        # funnel should say so.
        await mark_replied(container, chat_session_id)

        if _too_stale_to_answer(body):
            # Old enough that answering would mean replying to a conversation
            # that has long since moved on. Note this checks the message's own
            # age, NOT `body.synced`: Baileys flags every message WhatsApp
            # queued during a reconnect as "synced", so vetoing on that flag
            # silently dropped fresh campaign replies that happened to land
            # while the bridge was reconnecting — which on a free-tier host
            # that sleeps is most of them.
            log.info(
                "whatsapp.reply.skipped",
                session_id=str(ws.id),
                reason="stale",
                age_seconds=int(time.time()) - body.timestamp,
            )
            return {"status": "stale"}

        if effective_chatbot_id is None:
            # Linked but no assistant attached anywhere — receiving is fine,
            # replying would be answering on the user's behalf without them
            # asking.
            log.info("whatsapp.reply.skipped", session_id=str(ws.id), reason="no_assistant")
            return {"status": "no_assistant"}
        if not auto_reply:
            # A human has taken this conversation over.
            log.info("whatsapp.reply.skipped", session_id=str(ws.id), reason="paused")
            return {"status": "paused"}

        background.add_task(
            _reply_to_message,
            ws.tenant_id,
            chat_session_id,
            ws.id,
            effective_chatbot_id,
            body.jid,
            phone,
            body.text,
        )
        return {"status": "queued"}

    if body.event == "qr":
        ws.offer_qr(body.qr_data_url)
    elif body.event == "linked":
        ws.mark_linked(body.phone_number, body.display_name)
    elif body.event == "disconnected":
        ws.mark_disconnected(body.error)
    elif body.event == "logged_out":
        ws.mark_logged_out(body.error)
    elif body.event == "failed":
        ws.mark_failed(body.error)

    async with container.unit_of_work() as uow:
        uow.set_tenant_scope(ws.tenant_id)
        await uow.whatsapp_web_sessions.update(ws)
        await uow.commit()
    return {"status": "ok"}
