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

import uuid

from fastapi import APIRouter, BackgroundTasks, Header, HTTPException

from src.application.dtos import AskInput
from src.application.ports.repositories import WhatsAppConversation
from src.application.use_cases.ask_chatbot import AskChatbot
from src.config.container import get_container
from src.config.settings import get_settings
from src.domain.chat.entities import ChatSession
from src.domain.shared.identifiers import ChatbotId, SessionId, TenantId
from src.domain.whatsapp_web.entities import WhatsAppWebSession
from src.interfaces.api.deps import AdminPrincipalDep, ContainerDep
from src.interfaces.api.schemas import (
    AttachAssistantRequest,
    BridgeEventRequest,
    WhatsAppWebOptionsResponse,
    WhatsAppWebSessionResponse,
)

router = APIRouter(prefix="/whatsapp-web", tags=["whatsapp-web"])

# A linked personal account is deliberately inbound-only: it answers people who
# message it. Bulk outbound belongs on the official Twilio path, where the
# recipient consented — and it is what gets personal numbers banned.
_MAX_SESSIONS_PER_TENANT = 5


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
    still arrive and are stored, but nothing replies."""
    async with container.unit_of_work() as uow:
        uow.set_tenant_scope(principal.tenant_id)
        ws = await uow.whatsapp_web_sessions.get(principal.tenant_id, session_id)
        if ws is None:
            raise HTTPException(status_code=404, detail="Session not found")
        if body.chatbot_id is not None:
            bot = await uow.chatbots.get(principal.tenant_id, ChatbotId(body.chatbot_id))
            if bot is None:
                raise HTTPException(status_code=404, detail="Chatbot not found")
        ws.attach_chatbot(ChatbotId(body.chatbot_id) if body.chatbot_id else None)
        await uow.whatsapp_web_sessions.update(ws)
        await uow.commit()
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


# --- Bridge-facing (shared secret, no JWT) ---


async def _reply_to_message(
    tenant_id: TenantId,
    chatbot_id: ChatbotId,
    session_id: uuid.UUID,
    jid: str,
    phone: str,
    text: str,
) -> None:
    """Run the message through the assistant and send the answer back.

    A background task, not inline: retrieval plus generation takes seconds, and
    the bridge's event POST should return immediately so its socket handler
    isn't blocked behind the RAG pipeline.
    """
    container = get_container()

    # Reuse the existing WhatsApp conversation machinery so a linked personal
    # number gets the same multi-turn memory as a Twilio number, keyed on the
    # session id standing in for a channel id.
    async with container.unit_of_work() as uow:
        uow.set_tenant_scope(tenant_id)
        conversation = await uow.whatsapp_conversations.get(session_id, phone)
        if conversation is None:
            chat = ChatSession(tenant_id=tenant_id, chatbot_id=chatbot_id, title=phone)
            await uow.chats.add_session(chat)
            conversation = WhatsAppConversation(
                whatsapp_channel_id=session_id,
                phone_number=phone,
                session_id=chat.id,
            )
            await uow.whatsapp_conversations.add(conversation)
            await uow.commit()
        chat_session_id: SessionId = conversation.session_id
        auto_reply = conversation.auto_reply

    if not auto_reply:
        # Announce-only campaign — the reply is kept, not answered.
        return

    use_case = AskChatbot(container.unit_of_work(), container.embedder, container.llm)
    try:
        result = await use_case.execute(tenant_id, chat_session_id, AskInput(message=text))
        answer = result.answer
    except Exception:  # noqa: BLE001 — always answer, even on a pipeline failure
        answer = "Sorry, something went wrong on our end. Please try again shortly."

    await container.whatsapp_bridge.send_text(str(session_id), jid, answer)


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
        ws.heartbeat()
        async with container.unit_of_work() as uow:
            uow.set_tenant_scope(ws.tenant_id)
            await uow.whatsapp_web_sessions.update(ws)
            await uow.commit()
        if not ws.is_live():
            # Linked but no assistant attached — receiving is fine, replying
            # would be answering on the user's behalf without them asking.
            return {"status": "no_assistant"}
        assert ws.chatbot_id is not None
        background.add_task(
            _reply_to_message,
            ws.tenant_id,
            ws.chatbot_id,
            ws.id,
            body.jid,
            body.from_ or body.phone_number,
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
