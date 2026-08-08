"""Post-call dispatch: turn a finished conversation into a delivered payload.

Runs after a session is closed. For each configuration whose trigger statuses
match the outcome, it builds only the requested payload blocks (each optional
block costs one LLM call, so unchecked boxes are a real cost saving), records an
audit row, and delivers by webhook or email.

Failure policy: a broken destination is recorded against the delivery, never
raised. The conversation already happened; losing it because a customer's
endpoint is down would be strictly worse than a failed row in the log.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

import structlog

from src.application.ports.repositories import UnitOfWork
from src.application.ports.services import LLMProvider
from src.domain.chat.entities import Message
from src.domain.postcall.entities import CallStatus, PostCallConfig, PostCallDelivery
from src.domain.shared.identifiers import ChatbotId, SessionId, TenantId

log = structlog.get_logger(__name__)

# Cap what we feed the summarizer. A screening chat is short; a runaway session
# should not turn one dispatch into a five-figure token bill.
MAX_TRANSCRIPT_CHARS = 24_000

_SUMMARY_SYSTEM = (
    "You summarize completed recruiting conversations for a hiring team. "
    "Write 3-5 plain sentences covering: who the candidate is, what they were "
    "asked, what they answered, and what should happen next. State only what "
    "the transcript supports — never infer a qualification that wasn't said. "
    "Output prose only: no preamble, headings, or bullet points."
)

_SENTIMENT_SYSTEM = (
    "You assess a candidate's tone in a recruiting conversation. Reply with "
    'ONLY a JSON object: {"label": "positive"|"neutral"|"negative", '
    '"score": <float -1..1>, "rationale": "<one short sentence>"}. '
    "The score is the candidate's disposition, not the recruiter's: -1 is "
    "hostile or disengaged, 0 is neutral, 1 is enthusiastic."
)

_EXTRACTION_SYSTEM = (
    "You extract structured facts from a recruiting conversation. Reply with "
    "ONLY a JSON object with these keys: full_name, email, phone, position, "
    "years_experience, current_company, notice_period, salary_expectation, "
    "location. Use null for anything the candidate did not state — never guess, "
    "and never carry a value over from the recruiter's own questions."
)


@dataclass
class DispatchResult:
    dispatched: int
    skipped: int


def render_transcript(messages: list[Message]) -> str:
    """Timestamped, role-labelled transcript — the `Full Conversation` block."""
    lines = []
    for msg in messages:
        stamp = msg.created_at.astimezone(UTC).strftime("%Y-%m-%d %H:%M:%S UTC")
        speaker = "Candidate" if msg.role == "user" else "Assistant"
        lines.append(f"[{stamp}] {speaker}: {msg.content}")
    return "\n".join(lines)


def _clip(transcript: str) -> str:
    """Keep the *tail* when clipping — the end of a screening carries the
    outcome (availability, next steps), which matters more than the greeting."""
    if len(transcript) <= MAX_TRANSCRIPT_CHARS:
        return transcript
    return "…(earlier turns omitted)…\n" + transcript[-MAX_TRANSCRIPT_CHARS:]


def _parse_json_block(raw: str) -> dict | None:
    """Best-effort JSON from an LLM reply, tolerating ```json fences.

    Returns None rather than raising: a malformed extraction should degrade that
    one block, not sink the whole delivery.
    """
    text = raw.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[-1] if "\n" in text else text
        text = text.rsplit("```", 1)[0]
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        return None
    try:
        parsed = json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


class BuildPostCallPayload:
    """Assembles the payload blocks a config asked for."""

    def __init__(self, llm: LLMProvider) -> None:
        self._llm = llm

    async def execute(
        self,
        config: PostCallConfig,
        *,
        chatbot_name: str,
        session_id: SessionId,
        call_status: CallStatus,
        messages: list[Message],
        contact: dict | None = None,
    ) -> dict:
        transcript = render_transcript(messages)
        clipped = _clip(transcript)
        payload: dict = {
            "event": "post_call",
            "session_id": str(session_id),
            "chatbot": chatbot_name,
            "call_status": call_status,
            "message_count": len(messages),
            "started_at": messages[0].created_at.isoformat() if messages else None,
            "ended_at": datetime.now(UTC).isoformat(),
        }
        if contact:
            payload["contact"] = contact

        # An empty transcript (no-answer, failed send) still delivers — the
        # outcome itself is the signal — but there is nothing to analyse, so the
        # LLM blocks are skipped rather than asked to summarize silence.
        has_content = bool(messages)

        if config.include_transcript:
            payload["full_conversation"] = transcript
        if config.include_summary:
            payload["call_summary"] = (
                await self._ask(_SUMMARY_SYSTEM, clipped) if has_content else ""
            )
        if config.include_sentiment:
            payload["sentiment_analysis"] = (
                _parse_json_block(await self._ask(_SENTIMENT_SYSTEM, clipped))
                if has_content
                else None
            )
        if config.include_extracted:
            payload["extracted_information"] = (
                _parse_json_block(await self._ask(_EXTRACTION_SYSTEM, clipped))
                if has_content
                else None
            )
        return payload

    async def _ask(self, system: str, transcript: str) -> str:
        try:
            result = await self._llm.generate(system, f"<transcript>\n{transcript}\n</transcript>")
            return result.text.strip()
        except Exception as exc:  # noqa: BLE001 — one bad block must not sink the delivery
            log.warning("postcall.analysis_failed", error=str(exc))
            return ""


def _payload_to_html(payload: dict) -> str:
    """Email rendering. Blocks the config didn't ask for are simply absent."""
    rows = [f"<h2>Post-call report — {payload.get('chatbot', 'Assistant')}</h2>"]
    rows.append(
        f"<p><strong>Outcome:</strong> {payload.get('call_status')} &middot; "
        f"<strong>Messages:</strong> {payload.get('message_count', 0)}</p>"
    )
    contact = payload.get("contact")
    if contact:
        pretty = ", ".join(f"{k}: {v}" for k, v in contact.items() if v)
        rows.append(f"<p><strong>Contact:</strong> {pretty}</p>")
    if payload.get("call_summary"):
        rows.append(f"<h3>Summary</h3><p>{payload['call_summary']}</p>")
    if payload.get("sentiment_analysis"):
        s = payload["sentiment_analysis"]
        rows.append(
            f"<h3>Sentiment</h3><p>{s.get('label', 'unknown')} "
            f"({s.get('score', 'n/a')}) — {s.get('rationale', '')}</p>"
        )
    if payload.get("extracted_information"):
        items = "".join(
            f"<li><strong>{k}:</strong> {v}</li>"
            for k, v in payload["extracted_information"].items()
            if v not in (None, "")
        )
        rows.append(f"<h3>Extracted information</h3><ul>{items or '<li>None found</li>'}</ul>")
    if payload.get("full_conversation"):
        # <pre> keeps the timestamped line structure readable in a mail client.
        rows.append(
            "<h3>Full conversation</h3>"
            f"<pre style='white-space:pre-wrap;font-family:monospace;font-size:12px'>"
            f"{payload['full_conversation']}</pre>"
        )
    return "".join(rows)


class DispatchPostCall:
    """Fire every matching configuration for one finished session."""

    def __init__(
        self,
        uow: UnitOfWork,
        llm: LLMProvider,
        webhook_sender,
        email_sender,
        slack_sender=None,
    ) -> None:
        self._uow = uow
        self._llm = llm
        self._webhook = webhook_sender
        self._email = email_sender
        self._slack = slack_sender

    async def execute(
        self,
        tenant_id: TenantId,
        chatbot_id: ChatbotId,
        session_id: SessionId,
        call_status: CallStatus,
        *,
        contact: dict | None = None,
        only_config_id: uuid.UUID | None = None,
    ) -> DispatchResult:
        async with self._uow as uow:
            uow.set_tenant_scope(tenant_id)
            configs = await uow.post_call_configs.list_for_chatbot(tenant_id, chatbot_id)
            bot = await uow.chatbots.get(tenant_id, chatbot_id)
            messages = await uow.chats.list_messages(tenant_id, session_id)

        if only_config_id is not None:
            # "Send test" path: run exactly this rule, ignoring its triggers.
            matching = [c for c in configs if c.id == only_config_id]
        else:
            matching = [c for c in configs if c.triggers_on(call_status)]

        if not matching:
            return DispatchResult(dispatched=0, skipped=len(configs))

        chatbot_name = bot.name if bot else "Assistant"
        builder = BuildPostCallPayload(self._llm)
        dispatched = 0

        for config in matching:
            delivery = PostCallDelivery(
                tenant_id=tenant_id,
                chatbot_id=chatbot_id,
                config_id=config.id,
                session_id=session_id,
                call_status=call_status,
                delivery_method=config.delivery_method,
                destination=config.destination(),
            )
            # Reserve before doing any expensive work — if another worker already
            # dispatched this pair, we skip the LLM calls entirely.
            async with self._uow as uow:
                uow.set_tenant_scope(tenant_id)
                claimed = await uow.post_call_deliveries.claim(delivery)
                await uow.commit()
            if not claimed:
                log.info(
                    "postcall.already_dispatched",
                    config_id=str(config.id),
                    session_id=str(session_id),
                )
                continue

            payload = await builder.execute(
                config,
                chatbot_name=chatbot_name,
                session_id=session_id,
                call_status=call_status,
                messages=messages,
                contact=contact,
            )
            delivery.payload = payload

            if config.delivery_method == "webhook":
                ok, error = await self._webhook.send(config.webhook_url, payload)
            elif config.delivery_method == "slack":
                ok, error = await self._send_slack(tenant_id, payload)
            else:
                ok, error = await self._send_email(config, chatbot_name, payload)

            if ok:
                delivery.mark_delivered()
                dispatched += 1
            else:
                delivery.mark_failed(error)

            async with self._uow as uow:
                uow.set_tenant_scope(tenant_id)
                await uow.post_call_deliveries.finish(delivery)
                await uow.commit()

        return DispatchResult(dispatched=dispatched, skipped=len(configs) - len(matching))

    async def _send_slack(self, tenant_id: TenantId, payload: dict) -> tuple[bool, str]:
        """Deliver through whichever channel the tenant's Slack integration is
        wired to — the destination lives on the integration, not on this rule,
        so rotating the webhook fixes every post-call config at once."""
        if self._slack is None:
            return False, "Slack delivery isn't available on this server."
        async with self._uow as uow:
            uow.set_tenant_scope(tenant_id)
            connection = await uow.tenant_integrations.get(tenant_id, "slack")
        if connection is None or not connection.enabled or not connection.webhook_url():
            return False, "Slack isn't connected. Connect it on the Integrations page."
        # Block rendering belongs to the adapter — Slack's message format is an
        # infrastructure detail this layer shouldn't import.
        return await self._slack.send_post_call(connection.webhook_url(), payload)

    async def _send_email(
        self, config: PostCallConfig, chatbot_name: str, payload: dict
    ) -> tuple[bool, str]:
        if not getattr(self._email, "enabled", False):
            return False, "Email delivery is not configured on this server (RESEND_API_KEY)."
        try:
            sent = await self._email.send(
                to=config.email_to,
                subject=f"Post-call report — {chatbot_name} ({payload.get('call_status')})",
                html=_payload_to_html(payload),
            )
        except Exception as exc:  # noqa: BLE001 — same policy as the webhook path
            return False, f"Email provider error: {exc}"
        return (True, "") if sent else (False, "The email provider rejected the message.")
