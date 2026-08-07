"""Post-call delivery — what to send, where, and on which conversation outcome.

A chatbot may carry several independent configurations (e.g. "webhook the ATS on
every completed screening" plus "email the recruiter when one fails"), which is
why this is its own aggregate rather than a field on Chatbot.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Literal, get_args

from src.domain.shared.identifiers import ChatbotId, TenantId, new_id

# Mirrors the outcome vocabulary a telephony provider reports, so the same
# configuration works unchanged when a conversation arrives over the phone
# rather than over chat/WhatsApp. Chat sessions only ever produce `completed`
# or `failed`; broadcasts add `no_answer` and `failed`.
CallStatus = Literal["completed", "voicemail", "no_answer", "busy", "failed"]
ALL_CALL_STATUSES: tuple[CallStatus, ...] = get_args(CallStatus)

DeliveryMethod = Literal["webhook", "email"]
ALL_DELIVERY_METHODS: tuple[DeliveryMethod, ...] = get_args(DeliveryMethod)

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


@dataclass
class PostCallConfig:
    """One delivery rule. Inert until `enabled` and a valid destination."""

    tenant_id: TenantId
    chatbot_id: ChatbotId
    id: uuid.UUID = field(default_factory=new_id)
    delivery_method: DeliveryMethod = "webhook"
    # Exactly one of these is meaningful, selected by delivery_method.
    webhook_url: str = ""
    email_to: str = ""
    trigger_statuses: list[CallStatus] = field(default_factory=lambda: ["completed"])
    # Which blocks to compute and include. Each unchecked block is one fewer
    # LLM call at dispatch time, so these are a cost lever, not just a filter.
    include_summary: bool = True
    include_transcript: bool = True
    include_sentiment: bool = False
    include_extracted: bool = False
    enabled: bool = True
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def triggers_on(self, status: CallStatus) -> bool:
        return self.enabled and status in self.trigger_statuses

    def destination(self) -> str:
        return self.webhook_url if self.delivery_method == "webhook" else self.email_to

    def validation_error(self) -> str | None:
        """Human-readable reason this config can't be saved, or None if it can.

        Returned rather than raised so the API layer decides the status code and
        the UI can show the message inline against the field.
        """
        if self.delivery_method not in ALL_DELIVERY_METHODS:
            return f"Unknown delivery method '{self.delivery_method}'."
        if self.delivery_method == "webhook":
            url = self.webhook_url.strip()
            if not url:
                return "A webhook URL is required."
            if not url.startswith(("http://", "https://")):
                return "The webhook URL must start with http:// or https://."
        else:
            if not _EMAIL_RE.match(self.email_to.strip()):
                return "A valid destination email address is required."
        if not self.trigger_statuses:
            return "Select at least one call status to trigger on."
        unknown = [s for s in self.trigger_statuses if s not in ALL_CALL_STATUSES]
        if unknown:
            return f"Unknown call status: {', '.join(unknown)}."
        if not self.includes_anything():
            return "Select at least one item to include in the delivery."
        return None

    def includes_anything(self) -> bool:
        return any(
            (
                self.include_summary,
                self.include_transcript,
                self.include_sentiment,
                self.include_extracted,
            )
        )


@dataclass
class PostCallDelivery:
    """An attempted dispatch. Persisted so the UI can show what was sent, when,
    and why a delivery failed — post-call hooks are otherwise invisible."""

    tenant_id: TenantId
    chatbot_id: ChatbotId
    config_id: uuid.UUID
    session_id: uuid.UUID
    call_status: CallStatus
    id: uuid.UUID = field(default_factory=new_id)
    delivery_method: DeliveryMethod = "webhook"
    destination: str = ""
    status: str = "pending"  # pending | delivered | failed | skipped
    error: str = ""
    payload: dict = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def mark_delivered(self) -> None:
        self.status = "delivered"
        self.error = ""

    def mark_failed(self, error: str) -> None:
        self.status = "failed"
        self.error = error[:1000]
