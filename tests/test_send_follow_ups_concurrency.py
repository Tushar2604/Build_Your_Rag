"""SendFollowUps must be safe when two callers reach the same conversation at
once — which is exactly what production showed: the same nudge, delivered to
the same contact, two and three times within a couple of seconds.

The sweep-wide advisory lock (`_sweep_lease` in the API app) is supposed to
make two overlapping sweeps impossible, but it protects a *tick*, not a
conversation — and duplicates arriving seconds apart, not sweep-intervals
apart, point at something racing within or across individual sends rather than
two clean ticks. Rather than depend on diagnosing exactly how two callers
started, `lock_for_follow_up` makes the send itself safe under real
concurrency: whichever caller reaches the row first sends; the other is told
`None` and does nothing.

Hermetic: a fake "database" that models the one property that matters — a row
lock held by one transaction is invisible and unavailable to another — so the
safety property is exercised directly rather than inferred from reading the
code.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from src.application.ports.repositories import WhatsAppConversation
from src.application.use_cases.follow_up import SendFollowUps
from src.domain.shared.identifiers import SessionId, TenantId

AFTER = timedelta(minutes=5)
MAX = 2
NOW = datetime(2026, 8, 18, 12, 0, tzinfo=UTC)
TENANT = TenantId(uuid.uuid4())


def _conversation(**kw) -> WhatsAppConversation:  # type: ignore[no-untyped-def]
    defaults = {
        "whatsapp_channel_id": uuid.uuid4(),
        "phone_number": "+919122091018",
        "session_id": SessionId(uuid.uuid4()),
        "tenant_id": TENANT,
        "awaiting_reply_since": NOW - AFTER,
    }
    defaults.update(kw)
    return WhatsAppConversation(**defaults)


class _FakeBridge:
    """The QR-linked personal transport. Records every send it was asked to make."""

    enabled = True

    def __init__(self) -> None:
        self.sent: list[tuple[str, str, str]] = []

    async def send_text(self, session_id: str, jid: str, body: str):  # type: ignore[no-untyped-def]
        self.sent.append((session_id, jid, body))
        return True, ""


class _Session:
    def __init__(self, id: uuid.UUID) -> None:  # noqa: A002
        self.id = id
        self.status = "linked"
        # A real linked session always knows its handset, and the send path
        # reads it to check nothing else is answering for the same number.
        self.phone_number = "+919999000011"
        self.tenant_id = TENANT
        self.linked_at = NOW - timedelta(days=1)
        self.created_at = NOW - timedelta(days=1)


class _SharedConversationStore:
    """The "database": one conversation row, and a lock exactly one holder can
    have at a time. Whoever set `_locked_by` is the only one who can clear it
    — modelling that a real Postgres row lock is released by the transaction
    that holds it, not by whichever transaction happens to end first.
    """

    def __init__(self, conversation: WhatsAppConversation) -> None:
        self.row = conversation
        self._locked_by: object | None = None
        self.lock_attempts = 0
        self.updates: list[WhatsAppConversation] = []

    def lock(self, holder: object, conversation_id: uuid.UUID) -> WhatsAppConversation | None:
        self.lock_attempts += 1
        if self._locked_by is not None or conversation_id != self.row.id:
            return None
        self._locked_by = holder
        return self.row

    def release(self, holder: object) -> None:
        if self._locked_by is holder:
            self._locked_by = None

    def record_update(self, conversation: WhatsAppConversation) -> None:
        self.updates.append(conversation)
        self.row = conversation


class _ConversationsHandle:
    """The repository, from one caller's point of view — the exact method
    signatures `follow_up.py` calls, backed by the shared store above."""

    def __init__(self, store: _SharedConversationStore, holder: object) -> None:
        self._store = store
        self._holder = holder

    async def lock_for_follow_up(self, tenant_id, conversation_id):  # type: ignore[no-untyped-def]
        return self._store.lock(self._holder, conversation_id)

    async def update(self, conversation: WhatsAppConversation) -> None:
        self._store.record_update(conversation)

    def release(self) -> None:
        self._store.release(self._holder)


class _FakeWebSessions:
    def __init__(self, session: _Session) -> None:
        self._session = session
        # Every session linked to this handset, anywhere. One, unless a test
        # is describing the same phone connected in two places at once.
        self.everywhere: list[_Session] = [session]

    async def get(self, tenant_id, channel_id):  # type: ignore[no-untyped-def]
        return self._session

    async def list_linked_to_number_anywhere(self, phone_number):  # type: ignore[no-untyped-def]
        return [s for s in self.everywhere if s.phone_number == phone_number]


class _FakeChats:
    def __init__(self) -> None:
        self.added: list = []

    async def add_message(self, message) -> None:  # type: ignore[no-untyped-def]
        self.added.append(message)


class _FakeUow:
    """One caller's transaction. Two of these sharing one `_SharedConversationStore`
    is two racing processes sharing one database."""

    def __init__(self, store: _SharedConversationStore) -> None:
        self.whatsapp_conversations = _ConversationsHandle(store, holder=self)
        self.whatsapp_web_sessions = _FakeWebSessions(_Session(store.row.whatsapp_channel_id))
        self.chats = _FakeChats()
        self.scoped_to: TenantId | None = None

    async def __aenter__(self) -> _FakeUow:
        return self

    async def __aexit__(self, *args: object) -> None:
        # A real transaction releases only the locks it holds when it ends —
        # never one another transaction is still holding.
        self.whatsapp_conversations.release()
        return None

    def set_tenant_scope(self, tenant_id) -> None:  # type: ignore[no-untyped-def]
        self.scoped_to = tenant_id

    async def commit(self) -> None:
        return None


class TestTwoCallersRacingOnTheSameConversation:
    async def test_only_one_of_two_simultaneous_sends_goes_through(self) -> None:
        conversation = _conversation()
        store = _SharedConversationStore(conversation)
        bridge = _FakeBridge()

        first = SendFollowUps(_FakeUow(store), bridge=bridge, after=AFTER, max_follow_ups=MAX)
        second = SendFollowUps(_FakeUow(store), bridge=bridge, after=AFTER, max_follow_ups=MAX)

        # A third, unrelated transaction holds the lock first — standing in
        # for whatever "first" is doing in a real overlapping call. "second"
        # must be turned away, not merely delayed.
        interloper = object()
        store._locked_by = interloper
        result_second = await second._send_one(conversation, NOW)
        store.release(interloper)

        result_first = await first._send_one(conversation, NOW)

        assert result_second is False, "the caller that lost the race must not have sent anything"
        assert result_first is True, "the caller that wins the race must send"
        assert len(bridge.sent) == 1, f"expected exactly one WhatsApp send, got {len(bridge.sent)}"

    async def test_a_caller_that_loses_the_race_sends_no_message_at_all(self) -> None:
        conversation = _conversation()
        store = _SharedConversationStore(conversation)
        store._locked_by = object()  # someone else already has it
        bridge = _FakeBridge()
        use_case = SendFollowUps(_FakeUow(store), bridge=bridge, after=AFTER, max_follow_ups=MAX)

        sent = await use_case._send_one(conversation, NOW)

        assert sent is False
        assert bridge.sent == []
        assert store.updates == []

    async def test_the_lock_is_always_attempted_even_when_it_is_taken(self) -> None:
        # Guards against a "shortcut" that skips locking when the caller
        # already believes a conversation is due — the fresh, locked read is
        # the entire safety property, so it must not be optional.
        conversation = _conversation()
        store = _SharedConversationStore(conversation)
        store._locked_by = object()
        use_case = SendFollowUps(
            _FakeUow(store), bridge=_FakeBridge(), after=AFTER, max_follow_ups=MAX
        )

        await use_case._send_one(conversation, NOW)

        assert store.lock_attempts == 1

    async def test_a_transaction_never_releases_a_lock_it_did_not_acquire(self) -> None:
        # The fixture-correctness check for this whole file: if a losing
        # caller's cleanup could release the winner's lock, every test above
        # would pass for the wrong reason. Two losing attempts in a row must
        # leave the real holder's lock untouched.
        conversation = _conversation()
        store = _SharedConversationStore(conversation)
        holder = object()
        store._locked_by = holder
        bystander = SendFollowUps(
            _FakeUow(store), bridge=_FakeBridge(), after=AFTER, max_follow_ups=MAX
        )

        await bystander._send_one(conversation, NOW)
        await bystander._send_one(conversation, NOW)

        assert store._locked_by is holder


class TestTheReCheckInsideTheLock:
    """Even with no race at all, the row fetched under the lock — not the one
    handed in from the batch read — has to be what decides whether to send.
    """

    async def test_a_reply_that_arrived_after_the_batch_read_stops_the_send(self) -> None:
        stale = _conversation()  # what execute()'s batch read saw: due
        answered = _conversation(
            id=stale.id, awaiting_reply_since=None, followups_sent=0
        )  # what is true by the time the lock is taken: they replied
        store = _SharedConversationStore(answered)
        bridge = _FakeBridge()
        use_case = SendFollowUps(_FakeUow(store), bridge=bridge, after=AFTER, max_follow_ups=MAX)

        sent = await use_case._send_one(stale, NOW)

        assert sent is False
        assert bridge.sent == [], "a contact who has just replied must never be nudged"

    async def test_a_conversation_that_is_genuinely_due_is_sent_and_recorded(self) -> None:
        conversation = _conversation()
        store = _SharedConversationStore(conversation)
        bridge = _FakeBridge()
        use_case = SendFollowUps(_FakeUow(store), bridge=bridge, after=AFTER, max_follow_ups=MAX)

        sent = await use_case._send_one(conversation, NOW)

        assert sent is True
        assert len(bridge.sent) == 1
        assert store.updates[-1].followups_sent == 1

    async def test_the_lock_releases_after_a_successful_send_so_a_later_call_can_proceed(
        self,
    ) -> None:
        # Not a permanent hold: once this transaction commits, the row is free
        # again for the *next* legitimately due nudge (the second rung of the
        # ladder), not stuck locked forever.
        conversation = _conversation()
        store = _SharedConversationStore(conversation)
        bridge = _FakeBridge()
        use_case = SendFollowUps(_FakeUow(store), bridge=bridge, after=AFTER, max_follow_ups=MAX)

        await use_case._send_one(conversation, NOW)

        assert store._locked_by is None
