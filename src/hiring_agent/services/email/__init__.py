"""Isolated email service for the Hiring Agent.

No existing platform email abstraction was found, so this is a self-contained
port + adapters:

    base      — EmailSender port + SendReceipt
    mock      — MockEmailSender (current, no SMTP / no credentials)
    templates — the five hiring templates + render()

`build_email_sender()` is the single swap point. Today it returns a shared mock
sender (so its outbox persists across calls for inspection). When a real backend
lands, add an adapter satisfying EmailSender and select it here from settings.
"""

from __future__ import annotations

from src.hiring_agent.services.email.base import EmailSender, SendReceipt
from src.hiring_agent.services.email.mock import MockEmailSender
from src.hiring_agent.services.email.templates import available_templates, render

# Shared mock sender so its in-memory outbox accumulates across tool calls.
_MOCK_SENDER = MockEmailSender()


def build_email_sender(settings: object | None = None) -> EmailSender:
    """Return the active email sender.

    `settings` is accepted (currently unused) so the future real-backend swap is
    a one-line change here, e.g.:
        if getattr(settings, "smtp_enabled", False):
            return SmtpEmailSender(settings)
    """
    return _MOCK_SENDER


__all__ = [
    "EmailSender",
    "MockEmailSender",
    "SendReceipt",
    "available_templates",
    "build_email_sender",
    "render",
]
