"""WhatsApp Cloud API — Meta's business numbers.

The third way a WhatsApp message reaches this app, and the one meant for
production: a business number owned by the tenant, hosted by Meta, with no
sidecar process and no phone that has to stay online.

  | Path            | Owns the socket        | Identified by     |
  |-----------------|------------------------|-------------------|
  | whatsapp_web    | the Baileys bridge     | a linked handset  |
  | whatsapp (twilio)| Twilio                | the number itself |
  | **this module** | Meta                   | `phone_number_id` |

Three things here are not negotiable, and each replaces a way this endpoint
would otherwise fail in production:

**The signature.** The URL is public and unauthenticated by necessity — Meta
is the caller. `X-Hub-Signature-256`, verified against the app secret over the
*raw* body, is the only thing between an attacker and messages appearing in a
customer's thread. No secret configured means every delivery is refused, not
waved through.

**Answering fast.** Meta expects a 200 within seconds and retries what it does
not get, then throttles a subscription that keeps failing. A reply is a full
RAG or agent run — seconds to tens of seconds — so the work is queued and the
webhook returns immediately. Nothing about that is an optimisation: doing it
inline is how a working integration gets muted by Meta.

**Never failing loudly.** A 500 here is a retry, and a retry is a duplicate
message to a real person. Anything we cannot make sense of is logged and
answered 200, because there is nothing Meta can usefully do by sending it again.
"""

from __future__ import annotations

import time
import uuid

import structlog
from fastapi import APIRouter, BackgroundTasks, HTTPException, Query, Request, Response

from src.application.dtos import AskInput
from src.application.ports.repositories import WhatsAppChannel
from src.application.use_cases.ask_chatbot import AskChatbot
from src.application.use_cases.front_office import AskFrontOffice
from src.config.container import get_container
from src.config.settings import get_settings
from src.domain.chat.entities import Message, MessageRole
from src.domain.shared.identifiers import ChatbotId, SessionId, TenantId
from src.domain.shared.phone import canonical_phone
from src.infrastructure.messaging.whatsapp_cloud import (
    InboundMessage,
    parse_webhook,
    verification_challenge,
    verify_meta_signature,
)
from src.interfaces.api.deps import ContainerDep
from src.interfaces.api.routers.broadcasts import advance_delivery_status, mark_replied

# Shared with the personal-account path on purpose, not borrowed by accident:
# `_ensure_conversation` carries the one contact-identity rule (a number is
# canonicalised the same way by every writer, or the same person becomes two
# threads), and `_reply_gate` is a single per-process budget for auto-replies —
# two channels each with their own would exhaust the connection pool together
# while both looked well behaved.
from src.interfaces.api.routers.whatsapp_web import _ensure_conversation, _reply_gate

log = structlog.get_logger(__name__)

router = APIRouter(prefix="/whatsapp/cloud", tags=["whatsapp"])

# Meta's own vocabulary mapped onto the campaign funnel. `accepted` and
# `deleted` are deliberately absent — neither moves a recipient forward, and
# `advance_to` would reject them anyway.
_CLOUD_STATUS_MAP = {
    "sent": "sent",
    "delivered": "delivered",
    "read": "read",
    "failed": "failed",
}

# What the assistant says about a message it genuinely cannot read. Better than
# silence, which reads as the business ignoring you, and better than answering
# the caption of a photo nobody looked at.
_UNREADABLE = (
    "Thanks for that — I can only read text messages here. Could you type it "
    "out and I'll help right away?"
)


def webhook_url() -> str:
    """The single callback URL for every Cloud number on this deployment.

    One URL, not one per channel: the payload carries `phone_number_id`, which
    is what resolves the tenant, and Meta configures the callback per *app*
    rather than per number anyway.
    """
    return f"{get_settings().app_base_url.rstrip('/')}/api/v1/whatsapp/cloud/webhook"


# --- Meta's subscription handshake ------------------------------------------


@router.get("/webhook", include_in_schema=False)
async def verify_webhook(
    hub_mode: str = Query("", alias="hub.mode"),
    hub_verify_token: str = Query("", alias="hub.verify_token"),
    hub_challenge: str = Query("", alias="hub.challenge"),
) -> Response:
    """Meta calls this once, when the webhook is saved in the App Dashboard.

    Echo the challenge if the token matches. A plain-text body is required —
    Meta compares it literally, and a JSON-quoted challenge fails verification
    with no explanation beyond "the callback URL could not be validated".
    """
    settings = get_settings()
    challenge = verification_challenge(
        hub_mode, hub_verify_token, hub_challenge, settings.whatsapp_cloud_verify_token
    )
    if challenge is None:
        log.warning("whatsapp_cloud.verify_failed", mode=hub_mode)
        raise HTTPException(status_code=403, detail="Verification failed")
    log.info("whatsapp_cloud.verified")
    return Response(content=challenge, media_type="text/plain")


# --- Inbound ----------------------------------------------------------------


@router.post("/webhook", include_in_schema=False)
async def receive_webhook(
    request: Request, container: ContainerDep, background: BackgroundTasks
) -> dict[str, str]:
    settings = get_settings()
    raw = await request.body()

    if not settings.whatsapp_cloud_app_secret:
        # Refusing is the safe failure. Accepting unsigned posts because the
        # secret was never configured is a silent one, and the damage is real
        # messages to real customers.
        log.error("whatsapp_cloud.no_app_secret")
        raise HTTPException(
            status_code=503, detail="WhatsApp Cloud API is not configured on this deployment."
        )
    if not verify_meta_signature(
        raw,
        request.headers.get("X-Hub-Signature-256", ""),
        settings.whatsapp_cloud_app_secret,
    ):
        log.warning("whatsapp_cloud.bad_signature")
        raise HTTPException(status_code=403, detail="Invalid signature")

    try:
        payload = parse_webhook(await request.json())
    except ValueError:
        # Signed by Meta but not JSON we can read. Retrying will not change
        # that, so it is accepted and logged rather than bounced.
        log.warning("whatsapp_cloud.unparseable_body")
        return {"status": "ignored"}

    for status in payload.statuses:
        mapped = _CLOUD_STATUS_MAP.get(status.status.lower())
        if mapped:
            await advance_delivery_status(
                container,
                provider_message_id=status.message_id,
                status=mapped,
                error=status.error or f"Meta reported '{status.status}'.",
            )

    queued = 0
    for message in payload.messages:
        if await _handle_inbound(container, background, message):
            queued += 1

    return {"status": "ok", "queued": str(queued)}


async def _handle_inbound(container, background: BackgroundTasks, message: InboundMessage) -> bool:
    """Store one inbound message and, if appropriate, queue an answer.

    Store first, decide second — the same order the personal-account path
    learned the hard way. Every reason not to reply (no assistant, a human has
    taken the thread over, a message with no text) still leaves the operator a
    complete inbox; deciding first is how a conversation ends up invisible.
    """
    if not message.from_number:
        return False

    async with container.unit_of_work() as uow:
        channel = await uow.whatsapp_channels.get_by_phone_number_id(message.phone_number_id)
    if channel is None:
        # A number this deployment does not serve. Not an error — one Meta app
        # can front numbers connected to different environments — and answering
        # 200 stops Meta retrying something we will never accept.
        log.warning("whatsapp_cloud.unknown_number", phone_number_id=message.phone_number_id)
        return False

    phone = canonical_phone(message.from_number)

    async with container.unit_of_work() as uow:
        uow.set_tenant_scope(channel.tenant_id)
        conversation = await _ensure_conversation(
            uow,
            channel.tenant_id,
            channel.chatbot_id,
            channel.id,
            phone,
            message.contact_name,
        )
        # Meta redelivers anything it did not get a 200 for, so the message id
        # is what stops a slow reply turning into the same message twice in the
        # thread — and, worse, two answers to it.
        if message.message_id and await uow.chats.message_exists(
            channel.tenant_id, conversation.session_id, message.message_id
        ):
            await uow.commit()
            log.info("whatsapp_cloud.duplicate", message_id=message.message_id)
            return False

        await uow.chats.add_message(
            Message(
                session_id=conversation.session_id,
                tenant_id=channel.tenant_id,
                role=MessageRole.USER,
                content=message.text,
                provider_message_id=message.message_id or None,
            )
        )
        conversation.note_message(
            preview=message.text or f"[{message.kind}]", has_media=False, inbound=True
        )
        await uow.whatsapp_conversations.update(conversation)
        await uow.commit()
        session_id = conversation.session_id
        auto_reply = conversation.auto_reply

    # A reply on a campaign thread advances that recipient's funnel. A no-op
    # for ordinary inbound contacts, so it is called unconditionally.
    await mark_replied(container, session_id)

    if not auto_reply:
        # An announce-only campaign, or a colleague has taken this thread over.
        log.info("whatsapp_cloud.reply_skipped", reason="paused", phone=phone)
        return False

    background.add_task(
        _reply_to_message,
        channel.tenant_id,
        session_id,
        channel.id,
        channel.chatbot_id,
        phone,
        message.text,
        message.kind,
    )
    return True


async def _reply_to_message(
    tenant_id: TenantId,
    session_id: SessionId,
    channel_id: uuid.UUID,
    chatbot_id: ChatbotId,
    phone: str,
    text: str,
    kind: str,
) -> None:
    """Generate the answer and send it back through the Cloud API.

    Runs after the webhook has already answered Meta, so a failure here is
    invisible from both ends unless it is logged — which is exactly how "I
    connected a number and nothing ever replies" stays a mystery. Every branch
    logs.

    Held behind the shared reply bulkhead: inbound WhatsApp traffic is bursty
    (a campaign produces a cluster of replies within seconds), and each reply is
    a full pipeline holding a database connection while it calls a provider.
    Waiting here is backpressure, not loss — the message is already stored.
    """
    container = get_container()
    async with _reply_gate()():
        await _generate_and_send(
            container, tenant_id, session_id, channel_id, chatbot_id, phone, text, kind
        )


async def _generate_and_send(
    container,
    tenant_id: TenantId,
    session_id: SessionId,
    channel_id: uuid.UUID,
    chatbot_id: ChatbotId,
    phone: str,
    text: str,
    kind: str,
) -> None:
    async with container.unit_of_work() as uow:
        uow.set_tenant_scope(tenant_id)
        channel = await uow.whatsapp_channels.get(tenant_id, channel_id)
        bot = await uow.chatbots.get(tenant_id, chatbot_id)
    if channel is None:
        log.error("whatsapp_cloud.reply_failed", reason="channel_gone", phone=phone)
        return

    # A message with nothing to read — a photo, a location, a sticker. Answered
    # honestly rather than run through a pipeline that would have to invent what
    # it said.
    if not text.strip():
        await _send(container, channel, phone, _UNREADABLE, session_id, tenant_id)
        log.info("whatsapp_cloud.reply_unreadable", kind=kind, phone=phone)
        return

    # Which brain answers is the assistant's own setting, read per message
    # because it can change mid-thread. An assistant with appointments enabled
    # runs the front-office agent, which checks real availability and books;
    # everything else keeps the retrieval path. Without this branch a booking
    # assistant on this channel would answer with no tools at all — and a model
    # with no tools does not say "I can't book", it says "you're booked".
    books_appointments = bool(bot and bot.assistant.appointments_enabled)

    started = time.perf_counter()
    # Both use cases persist a successful answer themselves; a fallback bypasses
    # them and has to be written here, or the inbox shows the contact's message
    # with no sign of what they were sent back.
    persist_answer = False
    try:
        if books_appointments:
            reply = await AskFrontOffice(
                container.unit_of_work(), container.front_office_agent
            ).execute(
                tenant_id,
                session_id,
                message=text,
                chatbot_id=chatbot_id,
                source="whatsapp",
                channel="whatsapp",
                # So the agent can find "my appointments" without asking a
                # contact for the number they are messaging from.
                customer_phone=phone,
                persist_user_message=False,
            )
            answer = reply.answer
            mode = "front_office"
        else:
            result = await AskChatbot(
                container.unit_of_work(), container.embedder, container.llm
            ).execute(
                tenant_id,
                session_id,
                AskInput(message=text, persist_user_message=False, chatbot_id=chatbot_id),
            )
            answer = result.answer
            mode = "rag"
        log.info(
            "whatsapp_cloud.reply_generated",
            session_id=str(session_id),
            chatbot_id=str(chatbot_id),
            mode=mode,
            latency_ms=int((time.perf_counter() - started) * 1000),
        )
    except Exception as exc:  # noqa: BLE001 — always answer, even on a pipeline failure
        log.exception(
            "whatsapp_cloud.reply_failed",
            session_id=str(session_id),
            error=f"{type(exc).__name__}: {exc}",
        )
        answer = "Sorry, something went wrong on our end. Please try again shortly."
        persist_answer = True

    await _send(
        container, channel, phone, answer, session_id, tenant_id, persist=persist_answer
    )


async def _send(
    container,
    channel: WhatsAppChannel,
    phone: str,
    answer: str,
    session_id: SessionId,
    tenant_id: TenantId,
    *,
    persist: bool = False,
) -> None:
    """Send one reply and keep the inbox in step with what the contact sees."""
    ok, _message_id, error = await container.whatsapp_cloud_sender.send(
        phone_number_id=channel.phone_number_id,
        access_token=channel.access_token,
        to_number=phone,
        body=answer,
        api_version=get_settings().whatsapp_cloud_api_version,
    )
    if not ok:
        # The answer exists but never reached the contact. Advancing the thread
        # anyway would show the operator a message that was never delivered.
        log.error("whatsapp_cloud.send_failed", session_id=str(session_id), error=error)
        return

    async with container.unit_of_work() as uow:
        uow.set_tenant_scope(tenant_id)
        if persist:
            await uow.chats.add_message(
                Message(
                    session_id=session_id,
                    tenant_id=tenant_id,
                    role=MessageRole.ASSISTANT,
                    content=answer,
                    provider="whatsapp:assistant",
                )
            )
        conversation = await uow.whatsapp_conversations.get(channel.id, phone)
        if conversation is not None:
            conversation.note_message(preview=answer, has_media=False, inbound=False)
            await uow.whatsapp_conversations.update(conversation)
        await uow.commit()
