"""SendEmailTool — render and (mock-)send a hiring email template.

Runs IN-PROCESS through the isolated email service (EmailSender port). Today the
port resolves to MockEmailSender — no SMTP, no credentials, nothing leaves the
process. Templates: interview_invitation, reminder, rejection, selection, offer.

Inputs (via kwargs):
    template   : str        — one of the five template names
    recipients : list       — [{email, name, context}] or ["addr@x", ...] for a batch
    to         : str        — a single recipient (shorthand for recipients=[to])
    context    : dict       — shared template variables (role, company, interview_time, ...)
    from_addr  : str        — optional sender address
When no recipients are supplied (e.g. the workflow simulation passing only a
`template`/`top_n`), the tool returns a benign no-op.
"""

from __future__ import annotations

from typing import Any

import structlog

from src.application.agent.tools import ToolContext, ToolResult, ToolSpec

log = structlog.get_logger(__name__)

# Convenience aliases so callers using older/shorter names still resolve.
_TEMPLATE_ALIASES = {
    "interview_invite": "interview_invitation",
    "invite": "interview_invitation",
    "invitation": "interview_invitation",
    "select": "selection",
    "selected": "selection",
    "reject": "rejection",
}


class SendEmailTool:
    spec = ToolSpec(
        name="send_email",
        description=(
            "Render and send a hiring email using a named template "
            "(interview_invitation, reminder, rejection, selection, offer) to one "
            "or more recipients. Sending is mocked (no SMTP). Returns a per-"
            "recipient delivery receipt."
        ),
        parameters={
            "template": {
                "type": "string",
                "description": (
                    "Template: interview_invitation | reminder | rejection | "
                    "selection | offer."
                ),
            },
            "recipients": {
                "type": "array",
                "description": "Recipients: [{email, name, context}] or [\"addr\", ...].",
            },
            "to": {
                "type": "string",
                "description": "Single recipient address (shorthand for one-item recipients).",
            },
            "context": {
                "type": "object",
                "description": "Shared template variables (role, company, interview_time, ...).",
            },
        },
    )

    async def run(self, ctx: ToolContext, **kwargs: Any) -> ToolResult:
        recipients = self._resolve_recipients(kwargs)
        if not recipients:
            return ToolResult(
                observation=(
                    "No recipients supplied. Pass `recipients` or `to` (and a "
                    "`template`) to send email."
                ),
                data={"skipped": True},
                ok=True,
            )

        from src.hiring_agent.types import EmailTemplate

        template = self._resolve_template(kwargs.get("template"), EmailTemplate)
        if template is None:
            from src.hiring_agent.services.email import available_templates

            return ToolResult(
                observation=(
                    f"[send_email error] unknown template "
                    f"{kwargs.get('template')!r}. Valid: {', '.join(available_templates())}"
                ),
                data={"error": "unknown_template"},
                ok=False,
            )

        from src.hiring_agent.services.email import build_email_sender
        from src.hiring_agent.services.send_email_service import SendEmailService

        log.info(
            "hiring.tool.send_email.invoke",
            tenant=str(ctx.tenant_id),
            template=str(template),
            recipients=len(recipients),
        )

        try:
            service = SendEmailService(build_email_sender())
            result = await service.send(
                template,
                recipients,
                context=kwargs.get("context") or {},
                from_addr=kwargs.get("from_addr"),
            )
        except Exception as exc:  # noqa: BLE001 - surface as a handled tool error
            log.error("hiring.tool.send_email.failed", error=str(exc))
            return ToolResult(
                observation=f"[send_email error] {type(exc).__name__}: {exc}",
                data={"error": str(exc), "error_type": type(exc).__name__},
                ok=False,
            )

        observation = (
            f"Sent {result.sent}/{result.total} '{template.value}' email(s) "
            f"via {result.provider} sender."
        )
        return ToolResult(observation=observation, data=result.model_dump(mode="json"), ok=True)

    # ------------------------------------------------------------------
    # Input coercion
    # ------------------------------------------------------------------

    @staticmethod
    def _resolve_recipients(kwargs: dict[str, Any]) -> list[dict | str]:
        recipients = kwargs.get("recipients")
        if isinstance(recipients, list) and recipients:
            return recipients
        to = kwargs.get("to")
        if isinstance(to, str) and to.strip():
            return [to.strip()]
        if isinstance(to, dict):
            return [to]
        return []

    @staticmethod
    def _resolve_template(raw: Any, template_cls):  # type: ignore[no-untyped-def]
        if not isinstance(raw, str) or not raw.strip():
            return None
        value = raw.strip().lower()
        value = _TEMPLATE_ALIASES.get(value, value)
        try:
            return template_cls(value)
        except ValueError:
            return None
