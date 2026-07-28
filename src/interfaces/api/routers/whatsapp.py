"""WhatsApp channel — deploy a chatbot directly into WhatsApp via Twilio.

Admin-side CRUD is authenticated; the webhook is Twilio-only, verified via
its request signature (src/infrastructure/messaging/twilio_signature.py) —
no JWT/API key, since Twilio itself is the caller and the signature is keyed
to the connecting tenant's own Twilio Auth Token. The webhook reuses
AskChatbot exactly as the JSON (non-streaming) chat endpoint does — a thin
adapter, not a new RAG pipeline — so quota, guardrails, retrieval, and
persistence all come for free.
"""

from __future__ import annotations

import uuid
from xml.sax.saxutils import escape

from fastapi import APIRouter, HTTPException, Request, Response

from src.application.dtos import AskInput
from src.application.ports.repositories import WhatsAppChannel, WhatsAppConversation
from src.application.use_cases.ask_chatbot import AskChatbot
from src.config.settings import get_settings
from src.domain.chat.entities import ChatSession
from src.domain.shared.identifiers import ChatbotId
from src.infrastructure.messaging.twilio_signature import verify_twilio_signature
from src.interfaces.api.deps import ContainerDep, PrincipalDep
from src.interfaces.api.schemas import ConnectWhatsAppRequest, WhatsAppChannelResponse

router = APIRouter(prefix="/whatsapp", tags=["whatsapp"])


def _webhook_url() -> str:
    # One static URL for every channel — the webhook resolves which chatbot
    # to use by looking up the inbound "To" number, not from the URL path.
    return f"{get_settings().app_base_url.rstrip('/')}/api/v1/whatsapp/webhook"


def _to_response(channel: WhatsAppChannel, chatbot_name: str) -> WhatsAppChannelResponse:
    return WhatsAppChannelResponse(
        id=channel.id,
        chatbot_id=channel.chatbot_id,
        chatbot_name=chatbot_name,
        phone_number=channel.phone_number,
        status=channel.status,
        webhook_url=_webhook_url(),
        created_at=channel.created_at,
    )


def _twiml(message: str) -> Response:
    inner = f"<Message>{escape(message)}</Message>" if message else ""
    body = f'<?xml version="1.0" encoding="UTF-8"?><Response>{inner}</Response>'
    return Response(content=body, media_type="application/xml")


# --- Admin (authenticated) ---


@router.post("/channels", response_model=WhatsAppChannelResponse, status_code=201)
async def connect_whatsapp(
    body: ConnectWhatsAppRequest, principal: PrincipalDep, container: ContainerDep
) -> WhatsAppChannelResponse:
    async with container.unit_of_work() as uow:
        uow.set_tenant_scope(principal.tenant_id)
        bot = await uow.chatbots.get(principal.tenant_id, ChatbotId(body.chatbot_id))
        if bot is None:
            raise HTTPException(status_code=404, detail="Chatbot not found")

        already_this_bot = await uow.whatsapp_channels.get_by_chatbot(
            principal.tenant_id, ChatbotId(body.chatbot_id)
        )
        if already_this_bot is not None:
            raise HTTPException(
                status_code=409, detail="This chatbot is already connected to a WhatsApp number."
            )
        same_number = await uow.whatsapp_channels.get_by_phone_number(body.phone_number)
        if same_number is not None:
            raise HTTPException(
                status_code=409, detail="This phone number is already connected to another chatbot."
            )

        channel = WhatsAppChannel(
            tenant_id=principal.tenant_id,
            chatbot_id=ChatbotId(body.chatbot_id),
            phone_number=body.phone_number,
            twilio_account_sid=body.twilio_account_sid,
            twilio_auth_token=body.twilio_auth_token,
        )
        await uow.whatsapp_channels.add(channel)
        await uow.commit()
    return _to_response(channel, bot.name)


@router.get("/channels", response_model=list[WhatsAppChannelResponse])
async def list_whatsapp_channels(
    principal: PrincipalDep, container: ContainerDep
) -> list[WhatsAppChannelResponse]:
    async with container.unit_of_work() as uow:
        uow.set_tenant_scope(principal.tenant_id)
        channels = await uow.whatsapp_channels.list_for_tenant(principal.tenant_id)
        names: dict[uuid.UUID, str] = {}
        for ch in channels:
            bot = await uow.chatbots.get(principal.tenant_id, ch.chatbot_id)
            names[ch.id] = bot.name if bot else "Unknown assistant"
    return [_to_response(ch, names[ch.id]) for ch in channels]


@router.delete("/channels/{channel_id}", status_code=204)
async def disconnect_whatsapp(
    channel_id: uuid.UUID, principal: PrincipalDep, container: ContainerDep
) -> None:
    async with container.unit_of_work() as uow:
        uow.set_tenant_scope(principal.tenant_id)
        await uow.whatsapp_channels.delete(principal.tenant_id, channel_id)
        await uow.commit()


# --- Twilio webhook (public, signature-verified — no JWT/API key) ---


@router.post("/webhook", include_in_schema=False)
async def whatsapp_webhook(request: Request, container: ContainerDep) -> Response:
    form = await request.form()
    params = {k: str(v) for k, v in form.items()}
    to_number = params.get("To", "").replace("whatsapp:", "").strip()
    from_number = params.get("From", "").replace("whatsapp:", "").strip()
    body_text = params.get("Body", "").strip()
    signature = request.headers.get("X-Twilio-Signature", "")

    async with container.unit_of_work() as uow:
        channel = await uow.whatsapp_channels.get_by_phone_number(to_number)
    if channel is None:
        raise HTTPException(status_code=404, detail="Unknown WhatsApp number")

    if not verify_twilio_signature(_webhook_url(), params, signature, channel.twilio_auth_token):
        raise HTTPException(status_code=403, detail="Invalid Twilio signature")

    if not body_text or not from_number:
        return _twiml("")

    async with container.unit_of_work() as uow:
        uow.set_tenant_scope(channel.tenant_id)
        conversation = await uow.whatsapp_conversations.get(channel.id, from_number)
        if conversation is None:
            session = ChatSession(tenant_id=channel.tenant_id, chatbot_id=channel.chatbot_id)
            await uow.chats.add_session(session)
            conversation = WhatsAppConversation(
                whatsapp_channel_id=channel.id,
                phone_number=from_number,
                session_id=session.id,
            )
            await uow.whatsapp_conversations.add(conversation)
            await uow.commit()
        session_id = conversation.session_id

    use_case = AskChatbot(container.unit_of_work(), container.embedder, container.llm)
    try:
        result = await use_case.execute(channel.tenant_id, session_id, AskInput(message=body_text))
        answer = result.answer
    except Exception:  # noqa: BLE001 - a WhatsApp reply must always be sent, even on failure
        answer = "Sorry, something went wrong on our end. Please try again shortly."

    return _twiml(answer)
