"""Unit tests for the personal-WhatsApp session lifecycle.

The state machine is what the QR modal and the bridge's resume-on-boot sweep
both read, so the distinction between "dropped, will come back by itself" and
"revoked, needs a new QR" has to be exact — getting it wrong either strands a
working link or spins forever against one WhatsApp has already killed.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from src.domain.shared.identifiers import ChatbotId, TenantId, new_id
from src.domain.whatsapp_web.entities import QR_TTL_SECONDS, WhatsAppWebSession


def _session(**kwargs) -> WhatsAppWebSession:
    return WhatsAppWebSession(tenant_id=TenantId(new_id()), **kwargs)


def _linked() -> WhatsAppWebSession:
    ws = _session()
    ws.offer_qr("data:image/png;base64,AAA")
    ws.mark_linked("+917502163963", "Tushar")
    return ws


# --- Pairing ---


def test_a_new_session_starts_pending_and_wants_a_qr() -> None:
    ws = _session()
    assert ws.status == "pending"
    assert ws.needs_new_qr()
    assert not ws.qr_is_fresh()


def test_offering_a_qr_opens_the_scan_window() -> None:
    ws = _session()
    ws.offer_qr("data:image/png;base64,AAA")
    assert ws.status == "awaiting_scan"
    assert ws.qr_is_fresh()
    assert ws.qr_seconds_remaining() > 0
    assert not ws.needs_new_qr()


def test_an_expired_qr_is_not_fresh_and_needs_replacing() -> None:
    ws = _session()
    past = datetime.now(UTC) - timedelta(seconds=QR_TTL_SECONDS + 5)
    ws.offer_qr("data:image/png;base64,AAA", now=past)
    assert not ws.qr_is_fresh()
    assert ws.qr_seconds_remaining() == 0
    assert ws.needs_new_qr()


def test_linking_clears_the_qr() -> None:
    # A pairing code is single-use; serving it after the scan makes the next
    # scan fail with no explanation.
    ws = _linked()
    assert ws.status == "linked"
    assert ws.qr_data_url == ""
    assert ws.qr_expires_at is None
    assert ws.phone_number == "+917502163963"
    assert ws.linked_at is not None


# --- Disconnection semantics ---


def test_a_linked_session_that_drops_is_reconnectable_without_a_new_qr() -> None:
    ws = _linked()
    ws.mark_disconnected("socket closed")
    assert ws.status == "disconnected"
    assert ws.can_reconnect()
    assert not ws.needs_new_qr()


def test_a_never_linked_session_that_drops_is_a_failure_not_a_reconnect() -> None:
    # Calling this "disconnected" would show "reconnecting…" for a session that
    # has no credentials to reconnect with.
    ws = _session()
    ws.offer_qr("data:image/png;base64,AAA")
    ws.mark_disconnected("could not reach WhatsApp")
    assert ws.status == "failed"
    assert not ws.can_reconnect()
    assert ws.needs_new_qr()


def test_logout_is_terminal_and_demands_a_fresh_qr() -> None:
    ws = _linked()
    ws.mark_logged_out("device removed")
    assert ws.status == "logged_out"
    assert not ws.can_reconnect()
    assert ws.needs_new_qr()
    assert ws.qr_data_url == ""


def test_failure_records_a_clipped_reason() -> None:
    ws = _session()
    ws.mark_failed("x" * 5000)
    assert ws.status == "failed"
    assert len(ws.last_error) == 500


def test_relinking_clears_a_previous_error() -> None:
    ws = _linked()
    ws.mark_disconnected("network blip")
    ws.mark_linked("+917502163963", "Tushar")
    assert ws.last_error == ""
    assert ws.status == "linked"


# --- Readiness to answer ---


def test_a_linked_session_without_an_assistant_does_not_reply() -> None:
    # Receiving is fine; replying without the user picking an agent would be
    # answering on their behalf.
    ws = _linked()
    assert ws.chatbot_id is None
    assert not ws.is_live()
    assert "attach an assistant" in ws.health()


def test_attaching_an_assistant_makes_it_live() -> None:
    ws = _linked()
    ws.attach_chatbot(ChatbotId(new_id()))
    assert ws.is_live()
    assert ws.health() == "Connected"


def test_detaching_stops_replies_without_unlinking() -> None:
    ws = _linked()
    ws.attach_chatbot(ChatbotId(new_id()))
    ws.attach_chatbot(None)
    assert not ws.is_live()
    assert ws.status == "linked"


def test_a_disconnected_session_is_not_live_even_with_an_assistant() -> None:
    ws = _linked()
    ws.attach_chatbot(ChatbotId(new_id()))
    ws.mark_disconnected("socket closed")
    assert not ws.is_live()


@pytest.mark.parametrize(
    ("status", "fragment"),
    [
        ("awaiting_scan", "scan"),
        ("disconnected", "Reconnecting"),
        ("logged_out", "unlinked"),
        ("pending", "Starting"),
    ],
)
def test_health_explains_every_state(status: str, fragment: str) -> None:
    ws = _session()
    ws.status = status  # type: ignore[assignment]
    assert fragment.lower() in ws.health().lower()


def test_heartbeat_records_activity() -> None:
    ws = _linked()
    before = ws.last_seen_at
    ws.heartbeat()
    assert ws.last_seen_at is not None
    assert before is not None and ws.last_seen_at >= before


# --- Traffic as evidence of a live link ---
#
# Status is reported to us; traffic is observed. When the two disagree, traffic
# wins — a message can only arrive over a socket that is actually up. The
# failure this guards against is a row stuck at "disconnected" because a drop
# was recorded and the matching reconnect never reached the API: `is_live()`
# then refuses to answer anything, so the number keeps receiving forever and
# never replies, with nothing in the UI to suggest why.


def test_traffic_on_a_stale_disconnected_session_restores_it() -> None:
    ws = _linked()
    ws.attach_chatbot(ChatbotId(new_id()))
    ws.mark_disconnected("connection closed")
    assert not ws.is_live()

    ws.observe_traffic()

    assert ws.status == "linked"
    assert ws.is_live()
    assert ws.last_error == ""


def test_traffic_updates_last_seen_like_a_heartbeat() -> None:
    ws = _linked()
    ws.last_seen_at = None
    ws.observe_traffic()
    assert ws.last_seen_at is not None


def test_traffic_does_not_resurrect_a_logged_out_session() -> None:
    # WhatsApp revoked the link. A late event from a socket that has not
    # noticed yet must not put the row back into a state that claims it can
    # answer — recovering needs a new QR, and nothing else.
    ws = _linked()
    ws.mark_logged_out("device removed")
    ws.observe_traffic()
    assert ws.status == "logged_out"


def test_traffic_does_not_resurrect_a_failed_session() -> None:
    ws = _session()
    ws.mark_failed("bridge unreachable")
    ws.observe_traffic()
    assert ws.status == "failed"


def test_traffic_on_a_never_linked_session_changes_nothing() -> None:
    # `mark_disconnected` maps a never-linked drop to "failed", so this is
    # belt-and-braces: no path may promote a session that was never paired.
    ws = _session()
    ws.status = "disconnected"
    ws.observe_traffic()
    assert ws.status == "disconnected"


def test_a_live_session_stays_live_after_traffic() -> None:
    ws = _linked()
    ws.attach_chatbot(ChatbotId(new_id()))
    ws.observe_traffic()
    assert ws.status == "linked"
    assert ws.is_live()
