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
from src.domain.shared.phone import canonical_phone
from src.infrastructure.messaging.twilio_signature import verify_twilio_signature
from src.interfaces.api.deps import AdminPrincipalDep, ContainerDep
from src.interfaces.api.routers.broadcasts import mark_replied
from src.interfaces.api.routers.whatsapp_cloud import webhook_url as cloud_webhook_url
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
        provider=channel.provider,  # type: ignore[arg-type]
        status=channel.status,
        # Each provider has its own callback URL and its own idea of what goes
        # in it, so the one shown is the one this channel's operator has to
        # paste — handing a Twilio user Meta's URL is a support ticket.
        webhook_url=cloud_webhook_url() if channel.is_cloud else _webhook_url(),
        phone_number_id=channel.phone_number_id,
        setup_warning=_cloud_setup_warning() if channel.is_cloud else "",
        created_at=channel.created_at,
    )


def _cloud_setup_warning() -> str:
    """What is still missing on the deployment side, in the operator's words.

    Both of these live in the environment rather than on the channel, so a
    tenant can connect a number perfectly and still receive nothing. Saying so
    on the channel itself is the only place they will look when it happens.
    """
    settings = get_settings()
    missing = []
    if not settings.whatsapp_cloud_app_secret:
        missing.append("WHATSAPP_CLOUD_APP_SECRET")
    if not settings.whatsapp_cloud_verify_token:
        missing.append("WHATSAPP_CLOUD_VERIFY_TOKEN")
    if not missing:
        return ""
    return (
        "This deployment cannot receive WhatsApp Cloud messages yet — "
        f"{' and '.join(missing)} is not set. Inbound messages will be refused "
        "until it is."
    )


def _twiml(message: str) -> Response:
    inner = f"<Message>{escape(message)}</Message>" if message else ""
    body = f'<?xml version="1.0" encoding="UTF-8"?><Response>{inner}</Response>'
    return Response(content=body, media_type="application/xml")


# --- Admin (authenticated) ---


@router.post("/channels", response_model=WhatsAppChannelResponse, status_code=201)
async def connect_whatsapp(
    body: ConnectWhatsAppRequest, principal: AdminPrincipalDep, container: ContainerDep
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

        _require_credentials(body)

        if body.provider == "cloud":
            # Checked before the insert as well as by the unique index, so the
            # operator gets a sentence rather than a constraint violation. The
            # index is still what makes it true under a race.
            taken = await uow.whatsapp_channels.get_by_phone_number_id(body.phone_number_id)
            if taken is not None:
                raise HTTPException(
                    status_code=409,
                    detail="That WhatsApp phone number ID is already connected.",
                )

        channel = WhatsAppChannel(
            tenant_id=principal.tenant_id,
            chatbot_id=ChatbotId(body.chatbot_id),
            phone_number=body.phone_number,
            provider=body.provider,
            twilio_account_sid=body.twilio_account_sid,
            twilio_auth_token=body.twilio_auth_token,
            phone_number_id=body.phone_number_id.strip(),
            waba_id=body.waba_id.strip(),
            access_token=body.access_token.strip(),
        )
        await uow.whatsapp_channels.add(channel)
        await uow.commit()
    return _to_response(channel, bot.name)


def _require_credentials(body: ConnectWhatsAppRequest) -> None:
    """Each provider needs its own credentials, and neither needs the other's.

    Enforced here rather than in the schema because "required" depends on
    `provider` — and a channel saved without them is not a broken form, it is a
    number that silently never answers.
    """
    if body.provider == "cloud":
        missing = [
            name
            for name, value in (
                ("phone number ID", body.phone_number_id),
                ("access token", body.access_token),
            )
            if not value.strip()
        ]
    else:
        missing = [
            name
            for name, value in (
                ("Twilio Account SID", body.twilio_account_sid),
                ("Twilio Auth Token", body.twilio_auth_token),
            )
            if not value.strip()
        ]
    if missing:
        raise HTTPException(
            status_code=422,
            detail=f"Missing {' and '.join(missing)} for a {body.provider} number.",
        )


@router.get("/channels", response_model=list[WhatsAppChannelResponse])
async def list_whatsapp_channels(
    principal: AdminPrincipalDep, container: ContainerDep
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
    channel_id: uuid.UUID, principal: AdminPrincipalDep, container: ContainerDep
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

    # Twilio hands us "whatsapp:+91...". Canonicalised so this writer keys a
    # contact the same way the personal-WhatsApp and campaign paths do —
    # otherwise the same person is a different row on each.
    from_number = canonical_phone(from_number)

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
                tenant_id=channel.tenant_id,
            )
            await uow.whatsapp_conversations.add(conversation)
            await uow.commit()
        session_id = conversation.session_id
        auto_reply = conversation.auto_reply

    # If this number is on a broadcast, their reply advances the campaign funnel.
    # No-op otherwise, so ordinary inbound contacts are unaffected.
    await mark_replied(container, session_id)

    if not auto_reply:
        # An announce-only campaign. The reply is recorded above and shows in
        # the campaign funnel and the chat log; the assistant just stays quiet,
        # which is the whole difference between Broadcast and Broadcast + Reply.
        return _twiml("")

    use_case = AskChatbot(container.unit_of_work(), container.embedder, container.llm)
    try:
        result = await use_case.execute(channel.tenant_id, session_id, AskInput(message=body_text))
        answer = result.answer
    except Exception:  # noqa: BLE001 - a WhatsApp reply must always be sent, even on failure
        answer = "Sorry, something went wrong on our end. Please try again shortly."

    return _twiml(answer)
