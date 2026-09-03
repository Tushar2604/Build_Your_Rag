"""One handset, connected in two places — and only one of them speaks.

The reported thread: every automated nudge arrived twice, within the same
minute, all the way down the ladder — "Just checking in" twice, then "Still
happy to answer" twice, then the sign-off twice. Earlier in the same thread, one
customer message got two completely different answers: an English reply from a
dental receptionist and a Hindi one asking about HR.

That is not two bugs. WhatsApp's multi-device linking lets one phone keep
several companion devices connected at once, and it does not care whether they
belong to the same workspace. Two live bridge sessions on the same handset both
receive every inbound message, both generate their own reply, and both run their
own follow-up ladder. Neither knows the other exists.

`_absorb_duplicates` and `_sever_cross_tenant_collisions` already reconcile this
when a QR is scanned — but only then. They cannot reach a collision that was
already in the database, and nothing re-runs them, which is why the thread above
kept doubling long after that fix existed. So the question is asked again at the
point of effect, immediately before each send, by both paths that can send:

  * the reply path, in `bridge_events`,
  * the follow-up sweep, in `SendFollowUps`.

Going quiet is deliberately all that happens. Severing a session is destructive
and cross-tenant; it stays attached to somebody scanning a QR, which is a
deliberate human act, rather than to a message merely arriving.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from src.application.ports.repositories import WhatsAppConversation
from src.application.use_cases.follow_up import (
    FOLLOW_UP_MESSAGES,
    SendFollowUps,
)
from src.domain.shared.identifiers import SessionId, TenantId, new_id
from src.domain.whatsapp_web.entities import WhatsAppWebSession, answering_session
from src.interfaces.api.routers.whatsapp_web import _speaks_for_number

TENANT = TenantId(new_id())
OTHER_TENANT = TenantId(new_id())
NOW = datetime(2026, 9, 3, 12, 0, tzinfo=UTC)
HANDSET = "+919122091018"
AFTER = timedelta(minutes=5)
MAX = 2


def _session(
    *,
    tenant: TenantId = TENANT,
    linked_at: datetime | None = None,
    status: str = "linked",
    phone: str = HANDSET,
) -> WhatsAppWebSession:
    return WhatsAppWebSession(
        tenant_id=tenant,
        status=status,  # type: ignore[arg-type]
        phone_number=phone,
        linked_at=linked_at or NOW,
        created_at=linked_at or NOW,
    )


class TestWhichSessionSpeaksForAHandset:
    def test_the_most_recently_linked_one_wins(self) -> None:
        # Scanning a QR needs the phone in your hand, so the last person to do
        # it is the one who most recently decided where this number is answered.
        old = _session(linked_at=NOW - timedelta(days=2))
        new = _session(linked_at=NOW)
        assert answering_session([old, new]) is new
        assert answering_session([new, old]) is new, "order of the list is not a tiebreak"

    def test_it_reaches_the_same_answer_in_every_process(self) -> None:
        # Two sessions linked in the same instant must not be resolved
        # differently by two web workers, or both of them stay silent — or
        # worse, both keep talking.
        stamp = NOW
        first = _session(linked_at=stamp)
        second = _session(linked_at=stamp)
        assert answering_session([first, second]) is answering_session([second, first])

    def test_a_session_that_is_not_linked_does_not_get_a_vote(self) -> None:
        live = _session(linked_at=NOW - timedelta(days=2))
        dead = _session(linked_at=NOW, status="logged_out")
        assert answering_session([live, dead]) is live

    def test_nothing_linked_means_there_is_no_collision_to_resolve(self) -> None:
        assert answering_session([]) is None
        assert answering_session([_session(status="disconnected")]) is None

    def test_a_row_with_no_link_time_falls_back_to_when_it_was_made(self) -> None:
        # Rows predating `linked_at` must still be ranked, not crash the sweep.
        older = WhatsAppWebSession(
            tenant_id=TENANT,
            status="linked",
            phone_number=HANDSET,
            created_at=NOW - timedelta(days=3),
        )
        newer = _session(linked_at=NOW)
        assert answering_session([older, newer]) is newer

    def test_a_naive_timestamp_does_not_break_the_comparison(self) -> None:
        # Not every historical row came back from the driver timezone-aware.
        naive = WhatsAppWebSession(
            tenant_id=TENANT,
            status="linked",
            phone_number=HANDSET,
            linked_at=datetime(2026, 9, 1, 12, 0),
        )
        assert answering_session([naive, _session(linked_at=NOW)]) is not naive


# --- The reply path ---------------------------------------------------------


class _Sessions:
    def __init__(self, everywhere: list[WhatsAppWebSession]) -> None:
        self.everywhere = everywhere
        self.queries: list[str] = []

    async def list_linked_to_number_anywhere(self, phone_number: str):  # type: ignore[no-untyped-def]
        self.queries.append(phone_number)
        return [ws for ws in self.everywhere if ws.phone_number == phone_number]


class _Uow:
    def __init__(self, sessions: _Sessions) -> None:
        self.whatsapp_web_sessions = sessions

    async def __aenter__(self) -> _Uow:
        return self

    async def __aexit__(self, *args: object) -> None:
        return None


class _Container:
    def __init__(self, everywhere: list[WhatsAppWebSession]) -> None:
        self.sessions = _Sessions(everywhere)

    def unit_of_work(self) -> _Uow:
        return _Uow(self.sessions)


class TestTheReplyPathAnswersOnce:
    async def test_the_only_session_on_a_handset_answers(self) -> None:
        ws = _session()
        assert await _speaks_for_number(_Container([ws]), ws) is True

    async def test_the_newer_of_two_answers_and_the_older_goes_quiet(self) -> None:
        # The reported symptom, at its source: one message, two replies.
        old = _session(tenant=TENANT, linked_at=NOW - timedelta(days=1))
        new = _session(tenant=OTHER_TENANT, linked_at=NOW)
        container = _Container([old, new])

        assert await _speaks_for_number(container, new) is True
        assert await _speaks_for_number(container, old) is False

    async def test_two_sessions_in_the_same_workspace_are_deduplicated_too(self) -> None:
        # A re-scan that was never merged is the same collision, one tenant in.
        old = _session(linked_at=NOW - timedelta(hours=1))
        new = _session(linked_at=NOW)
        container = _Container([old, new])

        assert await _speaks_for_number(container, old) is False
        assert await _speaks_for_number(container, new) is True

    async def test_a_session_the_query_missed_still_counts_itself(self) -> None:
        # Traffic arriving is proof this socket is live even if the row still
        # says "disconnected" — losing the number to a stale twin because of a
        # missed reconnect event is how a working number goes permanently mute.
        mine = _session(status="disconnected", linked_at=NOW)
        stale = _session(linked_at=NOW - timedelta(days=5))
        assert await _speaks_for_number(_Container([stale]), mine) is True

    async def test_a_session_with_no_number_yet_is_left_alone(self) -> None:
        # Nothing to collide on, and nothing to look up.
        pending = _session(phone="", status="pending")
        container = _Container([])
        assert await _speaks_for_number(container, pending) is True
        assert container.sessions.queries == [], "no query is worth making here"

    async def test_a_different_handset_is_not_a_collision(self) -> None:
        mine = _session(phone="+919122091018")
        theirs = _session(phone="+919999999999", linked_at=NOW + timedelta(days=1))
        assert await _speaks_for_number(_Container([mine, theirs]), mine) is True


# --- The follow-up sweep ----------------------------------------------------


class _Bridge:
    enabled = True

    def __init__(self) -> None:
        self.sent: list[tuple[str, str, str]] = []

    async def send_text(self, session_id: str, jid: str, body: str):  # type: ignore[no-untyped-def]
        self.sent.append((session_id, jid, body))
        return True, ""


class _Conversations:
    def __init__(self, row: WhatsAppConversation) -> None:
        self.row = row
        self.updates: list[WhatsAppConversation] = []

    async def lock_for_follow_up(self, tenant_id, conversation_id):  # type: ignore[no-untyped-def]
        return self.row if conversation_id == self.row.id else None

    async def update(self, conversation: WhatsAppConversation) -> None:
        self.updates.append(conversation)


class _Chats:
    def __init__(self) -> None:
        self.added: list = []

    async def add_message(self, message) -> None:  # type: ignore[no-untyped-def]
        self.added.append(message)


class _Channels:
    async def get(self, tenant_id, channel_id):  # type: ignore[no-untyped-def]
        return None


class _SweepUow:
    def __init__(
        self,
        conversation: WhatsAppConversation,
        owner: WhatsAppWebSession | None,
        everywhere: list[WhatsAppWebSession],
    ) -> None:
        self._owner = owner
        self.whatsapp_conversations = _Conversations(conversation)
        self.whatsapp_web_sessions = _Sessions(everywhere)
        self.whatsapp_channels = _Channels()
        self.chats = _Chats()
        self.scoped_to: TenantId | None = None
        # `get` resolves the conversation's owning session; the port method
        # lives on the same repository as the collision lookup.
        self.whatsapp_web_sessions.get = self._get  # type: ignore[attr-defined]

    async def _get(self, tenant_id, channel_id):  # type: ignore[no-untyped-def]
        return self._owner

    async def __aenter__(self) -> _SweepUow:
        return self

    async def __aexit__(self, *args: object) -> None:
        return None

    def set_tenant_scope(self, tenant_id) -> None:  # type: ignore[no-untyped-def]
        self.scoped_to = tenant_id

    async def commit(self) -> None:
        return None


def _conversation(owner_id: uuid.UUID) -> WhatsAppConversation:
    return WhatsAppConversation(
        whatsapp_channel_id=owner_id,
        phone_number="+971500000001",
        session_id=SessionId(new_id()),
        tenant_id=TENANT,
        awaiting_reply_since=NOW - AFTER,
    )


class TestTheFollowUpSweepNudgesOnce:
    async def test_the_answering_session_still_nudges(self) -> None:
        owner = _session(linked_at=NOW)
        conversation = _conversation(owner.id)
        uow = _SweepUow(conversation, owner, [owner])
        bridge = _Bridge()

        sent = await SendFollowUps(
            uow, bridge=bridge, after=AFTER, max_follow_ups=MAX
        )._send_one(conversation, NOW)

        assert sent is True
        assert [body for _s, _j, body in bridge.sent] == [FOLLOW_UP_MESSAGES[0]]

    async def test_the_muted_session_sends_nothing(self) -> None:
        # The duplicate nudge, at its source. Both sessions are due, both hold
        # their own row lock, and the lock cannot help — these are two rows.
        muted = _session(tenant=TENANT, linked_at=NOW - timedelta(days=1))
        winner = _session(tenant=OTHER_TENANT, linked_at=NOW)
        conversation = _conversation(muted.id)
        uow = _SweepUow(conversation, muted, [muted, winner])
        bridge = _Bridge()

        sent = await SendFollowUps(
            uow, bridge=bridge, after=AFTER, max_follow_ups=MAX
        )._send_one(conversation, NOW)

        assert sent is False
        assert bridge.sent == [], "the contact must not be nudged twice"

    async def test_a_muted_thread_stops_asking_instead_of_retrying_forever(self) -> None:
        # Otherwise every sweep from now on picks this row up, fails, and logs.
        muted = _session(linked_at=NOW - timedelta(days=1))
        winner = _session(tenant=OTHER_TENANT, linked_at=NOW)
        conversation = _conversation(muted.id)
        uow = _SweepUow(conversation, muted, [muted, winner])

        await SendFollowUps(
            uow, bridge=_Bridge(), after=AFTER, max_follow_ups=MAX
        )._send_one(conversation, NOW)

        assert uow.whatsapp_conversations.updates, "the row must be written back"
        assert uow.whatsapp_conversations.updates[-1].awaiting_reply_since is None
        # Stopped, not signed off: the contact was sent nothing, so nothing is
        # booked against the ladder.
        assert uow.whatsapp_conversations.updates[-1].followups_sent == 0

    async def test_a_thread_whose_number_is_gone_also_stops(self) -> None:
        # A severed session leaves its conversations behind. They can never be
        # delivered to, and retrying them every sweep is noise, not resilience.
        conversation = _conversation(new_id())
        uow = _SweepUow(conversation, None, [])

        sent = await SendFollowUps(
            uow, bridge=_Bridge(), after=AFTER, max_follow_ups=MAX
        )._send_one(conversation, NOW)

        assert sent is False
        assert uow.whatsapp_conversations.updates[-1].awaiting_reply_since is None

    async def test_a_brief_disconnect_does_not_hand_contacts_to_an_older_twin(
        self,
    ) -> None:
        # Muting is permanent for the thread, so it must only ever happen to a
        # genuinely newer link. A socket that dropped for a minute is still the
        # rightful owner of its number.
        owner = _session(status="disconnected", linked_at=NOW)
        older_twin = _session(tenant=OTHER_TENANT, linked_at=NOW - timedelta(days=3))
        conversation = _conversation(owner.id)
        uow = _SweepUow(conversation, owner, [older_twin])

        await SendFollowUps(
            uow, bridge=_Bridge(), after=AFTER, max_follow_ups=MAX
        )._send_one(conversation, NOW)

        assert conversation.awaiting_reply_since is not None, "the ladder must survive"
        assert uow.whatsapp_conversations.updates == []

    async def test_a_transient_failure_is_still_retried(self) -> None:
        # The distinction that matters: someone briefly offline must not be
        # dropped the way a permanently undeliverable thread is.
        owner = _session(status="disconnected", linked_at=NOW)
        conversation = _conversation(owner.id)
        uow = _SweepUow(conversation, owner, [])

        sent = await SendFollowUps(
            uow, bridge=_Bridge(), after=AFTER, max_follow_ups=MAX
        )._send_one(conversation, NOW)

        assert sent is False
        assert conversation.awaiting_reply_since is not None, "the ladder must survive"
        assert uow.whatsapp_conversations.updates == []


@pytest.mark.parametrize("sessions", [[], [_session()], [_session(), _session()]])
def test_the_rule_never_raises_on_any_shape_of_input(
    sessions: list[WhatsAppWebSession],
) -> None:
    answering_session(sessions)
