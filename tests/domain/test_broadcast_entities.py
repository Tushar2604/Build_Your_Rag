"""Unit tests for the broadcast aggregate: phone normalization, the recipient
delivery funnel, message rendering, and campaign counters."""

from __future__ import annotations

import pytest
from src.domain.broadcast.entities import (
    MAX_MESSAGE_CHARS,
    Broadcast,
    BroadcastRecipient,
    normalize_phone,
)
from src.domain.shared.identifiers import ChatbotId, TenantId, new_id


def _broadcast(**kwargs) -> Broadcast:
    base = {
        "tenant_id": TenantId(new_id()),
        "chatbot_id": ChatbotId(new_id()),
        "whatsapp_channel_id": new_id(),
        "name": "BIM Str._India",
        "message_template": "Hi {{first_name}}, are you open to a BIM role in Dubai?",
    }
    return Broadcast(**{**base, **kwargs})


def _recipient(broadcast: Broadcast, **kwargs) -> BroadcastRecipient:
    base = {
        "broadcast_id": broadcast.id,
        "tenant_id": broadcast.tenant_id,
        "phone_number": "+917502163963",
    }
    return BroadcastRecipient(**{**base, **kwargs})


# --- Phone normalization ---


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("+91 75021 63963", "+917502163963"),
        ("whatsapp:+917502163963", "+917502163963"),
        ("+1 (415) 523-8886", "+14155238886"),
        ("00971553752665", "+971553752665"),
        ("917502163963", "+917502163963"),
    ],
)
def test_normalize_phone_accepts_common_shapes(raw: str, expected: str) -> None:
    assert normalize_phone(raw) == expected


@pytest.mark.parametrize("raw", ["", "not a number", "555-1234", "+0123456789", "12345"])
def test_normalize_phone_rejects_what_it_cannot_be_sure_of(raw: str) -> None:
    # A short local-looking number must NOT be guessed a country code for —
    # a wrong guess messages a stranger.
    assert normalize_phone(raw) is None


# --- Recipient funnel ---


def test_recipient_advances_forward_through_the_funnel() -> None:
    r = _recipient(_broadcast())
    r.mark_sent("SM123")
    assert r.status == "sent" and r.provider_message_id == "SM123" and r.attempts == 1
    assert r.advance_to("delivered")
    assert r.advance_to("read")
    assert r.status == "read"


def test_recipient_ignores_out_of_order_callbacks() -> None:
    # Twilio does not guarantee callback ordering; a late `sent` must not undo
    # a `read` that already arrived.
    r = _recipient(_broadcast())
    r.mark_sent("SM123")
    r.advance_to("read")
    assert not r.advance_to("sent")
    assert not r.advance_to("delivered")
    assert r.status == "read"


def test_duplicate_callback_reports_no_change() -> None:
    r = _recipient(_broadcast())
    r.mark_sent("SM1")
    assert r.advance_to("delivered")
    assert not r.advance_to("delivered")


def test_replied_outranks_read() -> None:
    r = _recipient(_broadcast())
    r.mark_sent("SM1")
    r.advance_to("read")
    assert r.advance_to("replied")
    assert r.status == "replied"


def test_unknown_status_is_rejected() -> None:
    r = _recipient(_broadcast())
    assert not r.advance_to("teleported")  # type: ignore[arg-type]
    assert r.status == "pending"


def test_async_undelivered_callback_does_not_inflate_the_attempt_count() -> None:
    # The message went out once. Counting the send AND the later "undelivered"
    # callback would make one attempt look like two, and a couple of retries
    # would then look like a number that had been hammered.
    r = _recipient(_broadcast())
    r.mark_sent("SM1")
    r.mark_undeliverable("recipient is not a WhatsApp user")
    assert r.status == "failed"
    assert r.attempts == 1
    assert "not a WhatsApp user" in r.error


def test_retry_requeues_but_keeps_the_attempt_count() -> None:
    # Keeping `attempts` is what stops a permanently bad number being retried
    # forever by an operator mashing the button.
    r = _recipient(_broadcast())
    r.mark_failed("not a WhatsApp user")
    assert r.status == "failed" and r.attempts == 1
    r.reset_for_retry()
    assert r.status == "pending" and r.error == "" and r.attempts == 1


# --- Message rendering ---


def test_render_substitutes_name_placeholders() -> None:
    b = _broadcast()
    r = _recipient(b, display_name="Mohammed Yacoob")
    assert b.render_message(r) == "Hi Mohammed, are you open to a BIM role in Dubai?"


def test_render_leaves_unknown_placeholders_visible() -> None:
    # A visible {{typo}} in a test send is far easier to catch than a silent "".
    b = _broadcast(message_template="Hello {{nickname}}")
    assert b.render_message(_recipient(b)) == "Hello {{nickname}}"


def test_render_clips_to_the_provider_limit() -> None:
    b = _broadcast(message_template="x" * (MAX_MESSAGE_CHARS + 500))
    assert len(b.render_message(_recipient(b))) == MAX_MESSAGE_CHARS


def test_render_handles_a_contact_with_no_name() -> None:
    b = _broadcast()
    assert b.render_message(_recipient(b)) == "Hi , are you open to a BIM role in Dubai?"


# --- Campaign state ---


def test_status_transitions() -> None:
    b = _broadcast()
    assert b.status == "queued" and not b.accepts_sends()
    b.start()
    assert b.status == "sending" and b.accepts_sends()
    b.pause()
    assert b.status == "paused" and not b.accepts_sends()
    b.start()  # resumable from paused
    assert b.status == "sending"
    b.complete()
    assert b.status == "completed"
    b.start()  # a completed campaign does not restart
    assert b.status == "completed"


def test_counts_are_cumulative_down_the_funnel() -> None:
    # This is what makes the filter chips read as a funnel rather than as
    # disjoint buckets: a `read` contact also counts as sent and delivered.
    b = _broadcast()
    recipients = []
    for status in ("read", "read", "delivered", "sent", "replied", "failed", "pending"):
        r = _recipient(b, phone_number=f"+9175021639{len(recipients):02d}")
        r.status = status  # type: ignore[assignment]
        recipients.append(r)
    b.recompute_counts(recipients)

    assert b.total_count == 7
    assert b.sent_count == 5      # read, read, delivered, sent, replied
    assert b.delivered_count == 4  # read, read, delivered, replied
    assert b.read_count == 3       # read, read, replied
    assert b.replied_count == 1
    assert b.failed_count == 1


def test_is_finished_only_when_nothing_is_pending() -> None:
    b = _broadcast()
    pending = _recipient(b, phone_number="+917502163901")
    done = _recipient(b, phone_number="+917502163902")
    done.status = "delivered"
    assert not b.is_finished([pending, done])
    pending.status = "failed"
    assert b.is_finished([pending, done])


def test_validation_rejects_an_unusable_campaign() -> None:
    assert _broadcast().validation_error() is None
    assert "name is required" in (_broadcast(name="  ").validation_error() or "")
    assert "message is required" in (_broadcast(message_template=" ").validation_error() or "")
