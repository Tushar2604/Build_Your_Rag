"""Hiring Agent — email types.

Provider-agnostic email value objects. Field shapes are generic enough to map
onto any future backend (SMTP, SendGrid, SES) without change.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field


class EmailTemplate(StrEnum):
    INTERVIEW_INVITATION = "interview_invitation"
    REMINDER = "reminder"
    REJECTION = "rejection"
    SELECTION = "selection"
    OFFER = "offer"


class EmailMessage(BaseModel):
    """A fully-rendered message handed to an EmailSender."""

    to: str
    subject: str
    body: str
    template: EmailTemplate
    from_addr: str = "no-reply@hiring.local"
    cc: list[str] = Field(default_factory=list)


class SendEmailResult(BaseModel):
    message_id: str
    to: str
    template: EmailTemplate
    subject: str
    status: str  # sent | queued | failed
    provider: str
    body_preview: str = ""


class SendEmailBatchResult(BaseModel):
    template: EmailTemplate
    total: int
    sent: int
    provider: str
    results: list[SendEmailResult] = Field(default_factory=list)
