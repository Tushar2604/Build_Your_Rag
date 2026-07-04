"""SendEmailService — render a template and send it to one or more recipients.

Depends only on the EmailSender port and the template renderer, so swapping the
mock backend for a real one requires no change here. Per-recipient context is
merged over a shared context, letting a single call personalize a batch.
"""

from __future__ import annotations

import structlog

from src.hiring_agent.services.email.base import EmailSender
from src.hiring_agent.services.email.templates import render
from src.hiring_agent.types.email import (
    EmailMessage,
    EmailTemplate,
    SendEmailBatchResult,
    SendEmailResult,
)

log = structlog.get_logger(__name__)

_DEFAULT_FROM = "no-reply@hiring.local"


class SendEmailService:
    def __init__(self, sender: EmailSender) -> None:
        self._sender = sender

    async def send(
        self,
        template: EmailTemplate,
        recipients: list[dict | str],
        context: dict | None = None,
        from_addr: str | None = None,
    ) -> SendEmailBatchResult:
        shared = context or {}
        results: list[SendEmailResult] = []
        sent = 0

        for raw in recipients:
            to, per_recipient_ctx = self._normalize_recipient(raw)
            if not to:
                continue
            merged = {**shared, **per_recipient_ctx}
            subject, body = render(template, merged)
            message = EmailMessage(
                to=to,
                subject=subject,
                body=body,
                template=template,
                from_addr=from_addr or _DEFAULT_FROM,
            )
            receipt = await self._sender.send(message)
            if receipt.status == "sent":
                sent += 1
            results.append(
                SendEmailResult(
                    message_id=receipt.message_id,
                    to=to,
                    template=template,
                    subject=subject,
                    status=receipt.status,
                    provider=receipt.provider,
                    body_preview=body[:160],
                )
            )

        log.info(
            "send_email.done",
            template=str(template),
            total=len(results),
            sent=sent,
            provider=self._sender.name,
        )
        return SendEmailBatchResult(
            template=template,
            total=len(results),
            sent=sent,
            provider=self._sender.name,
            results=results,
        )

    @staticmethod
    def _normalize_recipient(raw: dict | str) -> tuple[str, dict]:
        """Return (email, per-recipient context) from a str or dict recipient."""
        if isinstance(raw, str):
            return raw.strip(), {}
        if isinstance(raw, dict):
            to = str(raw.get("email") or raw.get("to") or "").strip()
            ctx = dict(raw.get("context") or {})
            # A bare `name` on the recipient personalizes the greeting.
            if raw.get("name") and "candidate_name" not in ctx:
                ctx["candidate_name"] = raw["name"]
            return to, ctx
        return "", {}
