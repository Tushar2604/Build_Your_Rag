"""A personal WhatsApp account linked by QR, via the multi-device protocol.

This is the "Phone WhatsApp" connection method: the user scans a QR from
WhatsApp → Linked Devices, and the platform becomes one of their linked
devices. Distinct from `WhatsAppChannel` (Twilio), which is an official Business
API number.

Two things are deliberately true of this aggregate:

  * It never holds the WhatsApp credentials. Those live in the bridge's own
    auth store, written by the Node service; this row only tracks lifecycle so
    the UI can show a QR, a countdown, and a linked state.
  * It is inbound-only by design. Bulk outbound from a linked personal account
    is what gets numbers banned, so broadcasts stay on the Twilio path.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Literal, get_args

from src.domain.shared.identifiers import ChatbotId, TenantId, new_id

# pending      -> row created, bridge hasn't produced a QR yet
# awaiting_scan-> a QR is available and still inside its short validity window
# linked       -> the phone scanned it; the socket is (or can be) live
# disconnected -> the socket dropped but the stored credentials are still valid,
#                 so it reconnects on its own without a re-scan
# logged_out   -> WhatsApp revoked the link (user removed the device, or a ban).
#                 Terminal: recovering needs a fresh QR.
# failed       -> the bridge couldn't start the session at all
SessionStatus = Literal[
    "pending", "awaiting_scan", "linked", "disconnected", "logged_out", "failed"
]
ALL_SESSION_STATUSES: tuple[SessionStatus, ...] = get_args(SessionStatus)

# WhatsApp rotates the pairing QR roughly every 20s and stops offering new ones
# after about a minute. The UI counts down against this and offers a refresh.
QR_TTL_SECONDS = 60

# Statuses from which a live socket is expected to exist or return by itself.
_SELF_HEALING: frozenset[str] = frozenset({"linked", "disconnected"})


@dataclass
class WhatsAppWebSession:
    tenant_id: TenantId
    id: uuid.UUID = field(default_factory=new_id)
    # The assistant that answers inbound messages. Null = messages are received
    # and stored but nothing replies, which is the safe default before the user
    # has explicitly chosen an agent.
    chatbot_id: ChatbotId | None = None
    status: SessionStatus = "pending"
    # E.164 of the linked handset, reported by WhatsApp after pairing.
    phone_number: str = ""
    display_name: str = ""
    qr_data_url: str = ""
    qr_expires_at: datetime | None = None
    last_error: str = ""
    linked_at: datetime | None = None
    last_seen_at: datetime | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def _touch(self) -> None:
        self.updated_at = datetime.now(UTC)

    # --- Lifecycle, driven by the bridge ---

    def offer_qr(self, data_url: str, *, now: datetime | None = None) -> None:
        """Publish a freshly minted pairing QR."""
        moment = now or datetime.now(UTC)
        self.qr_data_url = data_url
        self.qr_expires_at = moment + timedelta(seconds=QR_TTL_SECONDS)
        self.status = "awaiting_scan"
        self.last_error = ""
        self._touch()

    def mark_linked(self, phone_number: str, display_name: str = "") -> None:
        self.status = "linked"
        self.phone_number = phone_number
        self.display_name = display_name
        # Drop the QR immediately: it is single-use, and leaving it in the row
        # means it keeps being served to the browser after it stopped working.
        self.qr_data_url = ""
        self.qr_expires_at = None
        self.last_error = ""
        self.linked_at = datetime.now(UTC)
        self.last_seen_at = self.linked_at
        self._touch()

    def mark_disconnected(self, error: str = "") -> None:
        """A transient socket drop. Credentials survive, so no re-scan."""
        # A session that was never linked has nothing to reconnect with; calling
        # it "disconnected" would show a misleading "reconnecting…" state.
        self.status = "disconnected" if self.linked_at else "failed"
        self.last_error = error[:500]
        self._touch()

    def mark_logged_out(self, error: str = "") -> None:
        """WhatsApp revoked the link. Terminal until a new QR is scanned."""
        self.status = "logged_out"
        self.qr_data_url = ""
        self.qr_expires_at = None
        self.last_error = error[:500]
        self._touch()

    def mark_failed(self, error: str) -> None:
        self.status = "failed"
        self.qr_data_url = ""
        self.qr_expires_at = None
        self.last_error = error[:500]
        self._touch()

    def heartbeat(self) -> None:
        self.last_seen_at = datetime.now(UTC)
        self._touch()

    def observe_traffic(self) -> None:
        """Record that a real message just came over the socket.

        Traffic is stronger evidence than any status we were told about: it can
        only happen on a live link. A row left at "disconnected" — because the
        drop was reported and the matching reconnect was not — otherwise never
        answers again, since `is_live()` insists on "linked". Only that one
        recoverable state is promoted; "logged_out" and "failed" are decisions
        WhatsApp or the bridge made, and a stray event must not undo them.
        """
        if self.status == "disconnected" and self.linked_at is not None:
            self.status = "linked"
            self.last_error = ""
        self.heartbeat()

    def attach_chatbot(self, chatbot_id: ChatbotId | None) -> None:
        self.chatbot_id = chatbot_id
        self._touch()

    # --- Queries the API and UI ask ---

    def qr_is_fresh(self, *, now: datetime | None = None) -> bool:
        if not self.qr_data_url or self.qr_expires_at is None:
            return False
        return (now or datetime.now(UTC)) < self.qr_expires_at

    def qr_seconds_remaining(self, *, now: datetime | None = None) -> int:
        if self.qr_expires_at is None:
            return 0
        delta = (self.qr_expires_at - (now or datetime.now(UTC))).total_seconds()
        return max(0, int(delta))

    def is_live(self) -> bool:
        """Is this number set up to answer — linked, with an assistant chosen?

        A readiness question, for status copy and for tests. Deliberately *not*
        what the inbound path gates on: an arriving message is itself proof the
        socket is up, and gating the reply on this instead meant one missed
        reconnect event left a working number permanently mute. That path
        checks only whether an assistant is attached.
        """
        return self.status == "linked" and self.chatbot_id is not None

    def can_reconnect(self) -> bool:
        """True when the bridge should try to restore this session on boot —
        after a redeploy or a free-tier sleep — without a new QR."""
        return self.status in _SELF_HEALING and self.linked_at is not None

    def needs_new_qr(self) -> bool:
        return self.status in ("pending", "failed", "logged_out") or (
            self.status == "awaiting_scan" and not self.qr_is_fresh()
        )

    def health(self) -> str:
        """One line for the UI, so status copy isn't reinvented per surface."""
        if self.status == "linked":
            return (
                "Connected"
                if self.chatbot_id
                else "Connected — attach an assistant to start replying"
            )
        if self.status == "awaiting_scan":
            return "Waiting for you to scan the QR code"
        if self.status == "disconnected":
            return "Reconnecting — no re-scan needed"
        if self.status == "logged_out":
            return "This device was unlinked from WhatsApp. Scan again to reconnect."
        if self.status == "failed":
            return self.last_error or "Could not start the session"
        return "Starting up"


def answering_session(
    sessions: list[WhatsAppWebSession],
    *,
    assume_live: uuid.UUID | None = None,
) -> WhatsAppWebSession | None:
    """Of several live links to one handset, the one that speaks for it.

    WhatsApp's multi-device protocol lets a phone keep several companion
    devices connected at once, and it makes no promise that they belong to the
    same person — let alone the same workspace. Every one of them receives
    every inbound message. Our product has no concept of a shared number, so
    each connected session independently believed it was the one talking to
    that contact, generated its own answer, and sent it. The contact got two
    replies to one message, sometimes in two different languages from two
    different businesses' assistants, and later two of every automated nudge.

    Deduplicating at the *point of effect* is what makes this stop for links
    that already exist, rather than only for ones created after the fix — the
    reconciliation that runs when a QR is scanned cannot reach backwards, and
    nothing else re-runs it. Both the reply path and the follow-up sweep ask
    this question immediately before sending, so a collision goes quiet on the
    very next message instead of waiting for someone to re-scan.

    The most recently linked session wins. Scanning a QR needs physical access
    to the handset's WhatsApp app, so the person who did it last is the one who
    most recently decided where this number should be answered. Ties break on
    the id purely so every process in a deployment reaches the same answer.

    `assume_live` names a session to count as linked whatever its row last
    recorded. The reply path passes the session a message just arrived on:
    traffic can only happen over a live socket, and a row left at
    "disconnected" because the drop was reported and the reconnect was not
    would otherwise lose its own number to a stale twin — which is how a
    working number goes permanently mute rather than merely stopping
    duplicates.

    Returns None only when nothing here is linked at all, which is the caller's
    cue that there is no collision to resolve rather than that everyone loses.
    """
    live = [
        ws for ws in sessions if ws.status == "linked" or ws.id == assume_live
    ]
    if not live:
        return None
    return max(live, key=_link_rank)


def _link_rank(ws: WhatsAppWebSession) -> tuple[datetime, str]:
    """Sort key for "most recently linked". A session with no `linked_at` — a
    row from before that column was populated — sorts by when it was created,
    which is the closest honest answer available."""
    moment = ws.linked_at or ws.created_at
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    return (moment, str(ws.id))
