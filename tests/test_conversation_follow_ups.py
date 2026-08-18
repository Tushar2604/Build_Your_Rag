"""The follow-up ladder: nudge twice, sign off, then stop.

The rules worth pinning down are the ones that decide whether a real person
gets messaged: when a thread is due, when it is emphatically *not* due (they
replied, a human took over, the ladder is finished), and that a reply always
resets the whole thing. Getting any of these wrong means either pestering
somebody or never following up at all.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from src.application.ports.repositories import WhatsAppConversation
from src.domain.shared.identifiers import SessionId, TenantId

AFTER = timedelta(minutes=5)
MAX = 2
NOW = datetime(2026, 8, 18, 12, 0, tzinfo=UTC)


def _conversation(**kw) -> WhatsAppConversation:
    defaults = {
        "whatsapp_channel_id": uuid.uuid4(),
        "phone_number": "+919122091018",
        "session_id": SessionId(uuid.uuid4()),
        "tenant_id": TenantId(uuid.uuid4()),
    }
    defaults.update(kw)
    return WhatsAppConversation(**defaults)


def _due(conversation: WhatsAppConversation, *, now: datetime = NOW) -> bool:
    return conversation.follow_up_due(after=AFTER, max_follow_ups=MAX, now=now)


class TestWhenAFollowUpIsDue:
    def test_a_thread_nobody_is_waiting_on_is_never_due(self) -> None:
        # The resting state of most conversations: nothing outstanding.
        assert _due(_conversation()) is False

    def test_a_thread_inside_the_window_is_not_due_yet(self) -> None:
        c = _conversation(awaiting_reply_since=NOW - timedelta(minutes=4, seconds=59))
        assert _due(c) is False

    def test_a_thread_that_has_waited_the_full_window_is_due(self) -> None:
        c = _conversation(awaiting_reply_since=NOW - AFTER)
        assert _due(c) is True

    def test_a_thread_a_human_took_over_is_never_nudged(self) -> None:
        # auto_reply off means a person is handling this conversation; an
        # automated nudge would talk over them.
        c = _conversation(awaiting_reply_since=NOW - timedelta(hours=1), auto_reply=False)
        assert _due(c) is False

    def test_the_sign_off_is_still_owed_after_the_last_nudge(self) -> None:
        # At exactly the limit the two nudges are spent, but the closing
        # message has not been sent yet — so the thread is still due.
        c = _conversation(awaiting_reply_since=NOW - AFTER, followups_sent=MAX)
        assert _due(c) is True

    def test_a_signed_off_thread_is_never_picked_up_again(self) -> None:
        c = _conversation(awaiting_reply_since=NOW - timedelta(days=7), followups_sent=MAX + 1)
        assert _due(c) is False


class TestTheLadder:
    def test_the_first_two_sends_are_nudges_and_the_third_is_the_sign_off(self) -> None:
        c = _conversation(awaiting_reply_since=NOW - AFTER)
        assert c.is_final_follow_up(max_follow_ups=MAX) is False
        c.record_follow_up(final=False, now=NOW)

        assert c.followups_sent == 1
        assert c.is_final_follow_up(max_follow_ups=MAX) is False
        c.record_follow_up(final=False, now=NOW)

        assert c.followups_sent == 2
        assert c.is_final_follow_up(max_follow_ups=MAX) is True

    def test_a_nudge_restarts_the_clock_so_the_next_one_waits_a_full_window(self) -> None:
        c = _conversation(awaiting_reply_since=NOW - timedelta(hours=3))
        c.record_follow_up(final=False, now=NOW)

        assert c.awaiting_reply_since == NOW
        assert _due(c) is False, "the next nudge must wait its own window"
        assert _due(c, now=NOW + AFTER) is True

    def test_the_sign_off_stops_the_thread_waiting_on_anything(self) -> None:
        c = _conversation(awaiting_reply_since=NOW - AFTER, followups_sent=MAX)
        c.record_follow_up(final=True, now=NOW)

        assert c.awaiting_reply_since is None
        assert _due(c, now=NOW + timedelta(days=30)) is False


class TestRepliesResetEverything:
    def test_an_inbound_message_clears_the_ladder(self) -> None:
        # The whole point: someone who answers must never receive a nudge that
        # was queued up while they were quiet.
        c = _conversation(awaiting_reply_since=NOW - timedelta(hours=1), followups_sent=2)
        c.note_message(preview="sorry, was travelling", has_media=False, inbound=True)

        assert c.awaiting_reply_since is None
        assert c.followups_sent == 0
        assert _due(c, now=NOW + timedelta(days=1)) is False

    def test_a_reply_after_the_sign_off_makes_the_thread_eligible_again(self) -> None:
        c = _conversation(followups_sent=MAX + 1)
        c.note_message(preview="hi, still interested", has_media=False, inbound=True)
        c.note_message(preview="great — when suits you?", has_media=False, inbound=False)

        assert c.followups_sent == 0
        assert c.awaiting_reply_since is not None

    def test_anything_we_send_starts_the_clock(self) -> None:
        c = _conversation()
        c.note_message(preview="Hi, are you open to a new role?", has_media=False, inbound=False)

        assert c.awaiting_reply_since is not None
        assert _due(c, now=c.awaiting_reply_since + AFTER) is True
