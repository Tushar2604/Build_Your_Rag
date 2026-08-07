"""Broadcast campaign — an outbound WhatsApp send to many recipients, where
each reply is then handled by the chatbot's normal auto-reply pipeline.

The campaign owns *delivery*; the conversation that follows belongs to the
existing WhatsApp session machinery, so a recipient who replies gets the same
grounded, multi-turn assistant as any inbound contact. That split is why
`BroadcastRecipient` carries a `session_id` rather than its own message log.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Literal, get_args

from src.domain.shared.identifiers import ChatbotId, SessionId, TenantId, new_id

# queued  -> operator created it, nothing sent yet
# sending -> the send sweep is working through recipients
# paused  -> operator halted it; the sweep skips it, resumable
# completed -> every recipient reached a terminal state, or operator closed it
BroadcastStatus = Literal["queued", "sending", "paused", "completed"]

# Recipient lifecycle. `sent -> delivered -> read` are Twilio status-callback
# transitions; `replied` is ours, set when an inbound message arrives on that
# recipient's conversation. Only `failed` and `replied` are terminal-ish —
# a delivered message may still become `replied` later.
RecipientStatus = Literal["pending", "sent", "delivered", "read", "replied", "failed"]
ALL_RECIPIENT_STATUSES: tuple[RecipientStatus, ...] = get_args(RecipientStatus)

# Ranks the delivery funnel so an out-of-order Twilio callback (they are not
# ordered guarantees) can't move a recipient backwards from `read` to `sent`.
_STATUS_RANK: dict[str, int] = {
    "pending": 0,
    "sent": 1,
    "delivered": 2,
    "read": 3,
    "replied": 4,
    "failed": 5,  # terminal: only an explicit retry resets it
}

MAX_RECIPIENTS = 5000
MAX_MESSAGE_CHARS = 1600  # Twilio's per-message limit for WhatsApp

_E164_RE = re.compile(r"^\+[1-9]\d{6,15}$")


def normalize_phone(raw: str) -> str | None:
    """Coerce a pasted/CSV phone number to E.164, or None if it can't be.

    Deliberately conservative: strips separators and a leading `whatsapp:`, and
    accepts a bare `00` international prefix, but never *guesses* a country code
    for a local-looking number — a wrong guess messages a stranger.
    """
    s = raw.strip().replace("whatsapp:", "")
    s = re.sub(r"[\s\-().]", "", s)
    if s.startswith("00"):
        s = "+" + s[2:]
    if s and not s.startswith("+") and s.isdigit() and len(s) > 9:
        # Long digit run with no plus — common CSV export shape; assume the
        # country code is already there and just add the plus.
        s = "+" + s
    return s if _E164_RE.match(s) else None


@dataclass
class BroadcastRecipient:
    broadcast_id: uuid.UUID
    tenant_id: TenantId
    phone_number: str  # E.164, no "whatsapp:" prefix
    id: uuid.UUID = field(default_factory=new_id)
    display_name: str = ""
    status: RecipientStatus = "pending"
    error: str = ""
    provider_message_id: str = ""  # Twilio SID — how status callbacks find us
    session_id: SessionId | None = None  # set once a conversation exists
    attempts: int = 0
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def _touch(self) -> None:
        self.updated_at = datetime.now(UTC)

    def mark_sent(self, provider_message_id: str) -> None:
        self.status = "sent"
        self.provider_message_id = provider_message_id
        self.error = ""
        self.attempts += 1
        self._touch()

    def mark_failed(self, error: str) -> None:
        """The send itself was rejected — counts as an attempt."""
        self.status = "failed"
        self.error = error[:500]
        self.attempts += 1
        self._touch()

    def mark_undeliverable(self, error: str) -> None:
        """The provider accepted the send but later reported it undelivered.

        Deliberately does NOT increment `attempts`: the message went out once,
        and counting the callback separately would inflate the attempt count for
        every failure that arrives asynchronously rather than inline.
        """
        self.status = "failed"
        self.error = error[:500]
        self._touch()

    def advance_to(self, status: RecipientStatus) -> bool:
        """Apply a funnel transition, ignoring ones that would move backwards.

        Returns whether anything changed, so the caller can skip a pointless
        UPDATE on the (frequent) duplicate callback.
        """
        if status not in ALL_RECIPIENT_STATUSES:
            return False
        if _STATUS_RANK.get(status, 0) <= _STATUS_RANK.get(self.status, 0):
            return False
        self.status = status
        if status != "failed":
            self.error = ""
        self._touch()
        return True

    def reset_for_retry(self) -> None:
        """Put a failed recipient back in the queue. Keeps `attempts` so a
        permanently bad number doesn't get retried forever by an operator
        mashing the button."""
        self.status = "pending"
        self.error = ""
        self.provider_message_id = ""
        self._touch()


@dataclass
class Broadcast:
    tenant_id: TenantId
    chatbot_id: ChatbotId
    whatsapp_channel_id: uuid.UUID
    name: str
    message_template: str
    id: uuid.UUID = field(default_factory=new_id)
    status: BroadcastStatus = "queued"
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    # Denormalized funnel counters, maintained alongside recipient rows so the
    # campaign list doesn't need an aggregate query per row.
    total_count: int = 0
    sent_count: int = 0
    delivered_count: int = 0
    read_count: int = 0
    replied_count: int = 0
    failed_count: int = 0

    def _touch(self) -> None:
        self.updated_at = datetime.now(UTC)

    def render_message(self, recipient: BroadcastRecipient) -> str:
        """Substitute the supported placeholders. Unknown placeholders are left
        as-is rather than blanked — a visible `{{typo}}` in a test send is far
        easier to notice than a silent empty string."""
        first_name = (recipient.display_name or "").strip().split(" ")[0]
        return (
            self.message_template
            .replace("{{name}}", recipient.display_name.strip())
            .replace("{{first_name}}", first_name)
            .replace("{{phone}}", recipient.phone_number)
        )[:MAX_MESSAGE_CHARS]

    def validation_error(self) -> str | None:
        if not self.name.strip():
            return "Campaign name is required."
        if not self.message_template.strip():
            return "The broadcast message is required."
        if len(self.message_template) > MAX_MESSAGE_CHARS:
            return f"The message must be {MAX_MESSAGE_CHARS} characters or fewer."
        return None

    def start(self) -> None:
        if self.status in ("queued", "paused"):
            self.status = "sending"
            self._touch()

    def pause(self) -> None:
        if self.status == "sending":
            self.status = "paused"
            self._touch()

    def complete(self) -> None:
        self.status = "completed"
        self._touch()

    def accepts_sends(self) -> bool:
        return self.status == "sending"

    def recompute_counts(self, recipients: list[BroadcastRecipient]) -> None:
        """Rebuild the funnel counters from the recipient rows.

        Counters are cumulative down the funnel — a `read` recipient also counts
        as sent and delivered — which is what makes the filter chips read as a
        funnel ("Sent 33 / Delivered 33 / Read 31") rather than as disjoint
        buckets that don't sum to the total.
        """
        self.total_count = len(recipients)
        # `.get(..., 0)` rather than `[...]`: an unrecognised status persisted by
        # an older version must degrade to "not yet sent", not raise and take
        # the whole campaign view down.
        rank = lambda status: _STATUS_RANK.get(status, 0)  # noqa: E731
        reached = [r for r in recipients if r.status != "failed"]
        self.sent_count = sum(1 for r in reached if rank(r.status) >= _STATUS_RANK["sent"])
        delivered = _STATUS_RANK["delivered"]
        self.delivered_count = sum(1 for r in reached if rank(r.status) >= delivered)
        self.read_count = sum(1 for r in reached if rank(r.status) >= _STATUS_RANK["read"])
        self.replied_count = sum(1 for r in reached if r.status == "replied")
        self.failed_count = sum(1 for r in recipients if r.status == "failed")
        self._touch()

    def is_finished(self, recipients: list[BroadcastRecipient]) -> bool:
        """True when no recipient is still awaiting a send attempt."""
        return not any(r.status == "pending" for r in recipients)
