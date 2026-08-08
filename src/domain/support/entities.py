"""Issue reports — bug reports and feature requests submitted from the app."""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Literal, get_args

from src.domain.shared.identifiers import TenantId, new_id

ReportType = Literal["bug", "feature_request", "question", "billing", "other"]
ALL_REPORT_TYPES: tuple[ReportType, ...] = get_args(ReportType)

REPORT_TYPE_LABELS: dict[ReportType, str] = {
    "bug": "Bug — something is broken",
    "feature_request": "Feature request",
    "question": "Question / how do I…",
    "billing": "Billing or account",
    "other": "Other",
}

Priority = Literal["low", "medium", "high", "critical"]
ALL_PRIORITIES: tuple[Priority, ...] = get_args(Priority)

PRIORITY_LABELS: dict[Priority, str] = {
    "low": "Low — minor inconvenience",
    "medium": "Medium — important",
    "high": "High — blocking my work",
    "critical": "Critical — production is down",
}

# open -> the team hasn't looked yet; the rest are set by whoever triages.
IssueStatus = Literal["open", "in_progress", "resolved", "closed"]

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
# Permissive on purpose: a report should never be rejected over phone
# formatting. We only reject something that clearly isn't a number at all.
_PHONE_RE = re.compile(r"^\+?[\d\s\-().]{6,24}$")

MAX_DESCRIPTION = 5000


@dataclass
class IssueReport:
    tenant_id: TenantId
    name: str
    email: str
    report_type: ReportType
    subject: str
    description: str
    id: uuid.UUID = field(default_factory=new_id)
    phone: str = ""
    priority: Priority = "medium"
    status: IssueStatus = "open"
    # Captured automatically so the team doesn't have to ask "which page?".
    page_url: str = ""
    user_agent: str = ""
    email_sent: bool = False
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def validation_error(self) -> str | None:
        """Human-readable reason this can't be submitted, or None.

        Returned rather than raised so the API picks the status code and the
        form can show the message against the offending field.
        """
        if not self.name.strip():
            return "Your name is required."
        if not _EMAIL_RE.match(self.email.strip()):
            return "A valid email address is required so we can reply."
        if self.phone.strip() and not _PHONE_RE.match(self.phone.strip()):
            return "That phone number doesn't look right."
        if self.report_type not in ALL_REPORT_TYPES:
            return "Choose what kind of report this is."
        if self.priority not in ALL_PRIORITIES:
            return "Choose a priority."
        if not self.subject.strip():
            return "A short summary is required."
        if len(self.description.strip()) < 20:
            # A one-word "broken" costs a round-trip to triage; ask up front.
            return "Please describe the issue in at least 20 characters."
        if len(self.description) > MAX_DESCRIPTION:
            return f"The description must be {MAX_DESCRIPTION} characters or fewer."
        return None

    def normalized(self) -> IssueReport:
        self.name = self.name.strip()[:160]
        self.email = self.email.strip()[:320]
        self.phone = self.phone.strip()[:32]
        self.subject = self.subject.strip()[:200]
        self.description = self.description.strip()[:MAX_DESCRIPTION]
        self.page_url = self.page_url.strip()[:500]
        self.user_agent = self.user_agent.strip()[:500]
        return self

    def email_subject(self) -> str:
        """Leads with priority and type so an inbox rule can route on it."""
        return f"[{self.priority.upper()}] {REPORT_TYPE_LABELS[self.report_type]} — {self.subject}"
