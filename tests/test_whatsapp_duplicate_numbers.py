"""Guard: connecting the same WhatsApp number twice gives you one number.

The reported symptom: scan the QR again — because the link dropped, or because
you were not sure it had worked — and the workspace grows a second entry for the
same handset. Both say the same phone number, and the history is split between
them: the threads you remember are under the old one, and everything arriving
now lands under the new one.

The cause is that a session id is minted before the phone number is known. The
row has to exist for the bridge to pair against, so there is no way to
deduplicate up front — the earliest moment the collision is even visible is the
`linked` event that finally reports which handset scanned.

Direction matters and is not arbitrary. The NEW session is the survivor: the
bridge's stored credentials and its open socket are both keyed to that id, so
retiring it would leave a tidy-looking inbox that has quietly stopped receiving
anything. The old row's conversations move across to it instead.
"""

from __future__ import annotations

import asyncio
import uuid

from src.domain.shared.identifiers import ChatbotId, TenantId, new_id
from src.domain.whatsapp_web.entities import WhatsAppWebSession
from src.interfaces.api.routers.whatsapp_web import (
    _absorb_duplicates,
    _absorb_session,
    _digits,
)

TENANT = TenantId(new_id())


class _Conversations:
    """Records the re-pointing rather than performing it — the SQL half is
    exercised by the repository, what matters here is which way round it went
    and with which ids."""

    def __init__(self, moved: int = 3) -> None:
        self.moved = moved
        self.calls: list[tuple[uuid.UUID, uuid.UUID]] = []

    async def reassign_owner(self, tenant_id, from_owner_id, to_owner_id) -> int:
        self.calls.append((from_owner_id, to_owner_id))
        return self.moved


class _Sessions:
    def __init__(self, rows: list[WhatsAppWebSession]) -> None:
        self.rows = rows
        self.updated: list[WhatsAppWebSession] = []
        self.deleted: list[uuid.UUID] = []

    async def list_linked_to_number(self, tenant_id, phone_number):
        wanted = _digits(phone_number)
        return [r for r in self.rows if _digits(r.phone_number) == wanted]

    async def update(self, ws) -> None:
        self.updated.append(ws)

    async def delete(self, tenant_id, session_id) -> None:
        self.deleted.append(session_id)
        self.rows = [r for r in self.rows if r.id != session_id]


class _Uow:
    def __init__(self, sessions: _Sessions, conversations: _Conversations) -> None:
        self.whatsapp_web_sessions = sessions
        self.whatsapp_conversations = conversations

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc) -> None:
        return None

    def set_tenant_scope(self, tenant_id) -> None:
        pass

    async def commit(self) -> None:
        pass


class _Bridge:
    def __init__(self, fails: bool = False) -> None:
        self.fails = fails
        self.logged_out: list[str] = []

    async def logout_session(self, session_id: str) -> None:
        self.logged_out.append(session_id)
        if self.fails:
            raise RuntimeError("bridge unreachable")


class _Container:
    def __init__(self, sessions: _Sessions, conversations: _Conversations, bridge: _Bridge):
        self._uow = _Uow(sessions, conversations)
        self.whatsapp_bridge = bridge

    def unit_of_work(self):
        return self._uow


def _session(phone: str, *, chatbot_id: ChatbotId | None = None) -> WhatsAppWebSession:
    ws = WhatsAppWebSession(tenant_id=TENANT, chatbot_id=chatbot_id)
    ws.mark_linked(phone)
    return ws


# --- what counts as the same number ------------------------------------------


def test_the_same_handset_is_recognised_across_formatting() -> None:
    # WhatsApp reports whatever shape the handset registered, so string
    # equality is exactly the comparison that misses the duplicate.
    assert _digits("+971 50 123 4567") == _digits("971501234567") == "971501234567"


def test_two_different_numbers_are_not_confused() -> None:
    assert _digits("+971501234567") != _digits("+971501234568")


def test_a_session_with_no_number_yet_matches_nothing() -> None:
    # A pending session has an empty phone number, and treating every pending
    # row as "the same number" would merge sessions that are still pairing.
    assert _digits("") == ""


# --- the merge itself ---------------------------------------------------------


def test_history_moves_to_the_session_holding_the_live_socket() -> None:
    keeper, stale = _session("+971501234567"), _session("971501234567")
    conversations = _Conversations()
    sessions = _Sessions([keeper, stale])
    container = _Container(sessions, conversations, _Bridge())

    moved = asyncio.run(_absorb_session(container, keeper, stale))

    assert moved == 3
    # Old -> new, never the reverse: the new row is the one the bridge can
    # actually receive on.
    assert conversations.calls == [(stale.id, keeper.id)]
    assert sessions.deleted == [stale.id]


def test_the_old_device_is_unlinked_at_whatsapp() -> None:
    # Left alone, the handset keeps listing a linked device nothing reads.
    keeper, stale = _session("+971501234567"), _session("971501234567")
    bridge = _Bridge()
    container = _Container(_Sessions([keeper, stale]), _Conversations(), bridge)

    asyncio.run(_absorb_session(container, keeper, stale))

    assert bridge.logged_out == [str(stale.id)]


def test_an_unreachable_bridge_still_removes_the_duplicate_row() -> None:
    # Otherwise the number stays visibly doubled in the UI until someone
    # happens to retry, which is the bug this whole file is about.
    keeper, stale = _session("+971501234567"), _session("971501234567")
    sessions = _Sessions([keeper, stale])
    container = _Container(sessions, _Conversations(), _Bridge(fails=True))

    asyncio.run(_absorb_session(container, keeper, stale))

    assert sessions.deleted == [stale.id]


def test_the_assistant_already_chosen_for_the_number_carries_over() -> None:
    # Picking an assistant is a decision about the number, not about the
    # session row that happened to be current when it was made.
    bot = ChatbotId(new_id())
    keeper = _session("+971501234567")
    stale = _session("971501234567", chatbot_id=bot)
    container = _Container(_Sessions([keeper, stale]), _Conversations(), _Bridge())

    asyncio.run(_absorb_session(container, keeper, stale))

    assert keeper.chatbot_id == bot


def test_a_choice_on_the_new_session_is_not_overwritten() -> None:
    new_bot, old_bot = ChatbotId(new_id()), ChatbotId(new_id())
    keeper = _session("+971501234567", chatbot_id=new_bot)
    stale = _session("971501234567", chatbot_id=old_bot)
    container = _Container(_Sessions([keeper, stale]), _Conversations(), _Bridge())

    asyncio.run(_absorb_session(container, keeper, stale))

    assert keeper.chatbot_id == new_bot


# --- what runs at link time ---------------------------------------------------


def test_linking_a_number_absorbs_the_row_that_already_had_it() -> None:
    keeper, stale = _session("+971501234567"), _session("971501234567")
    conversations = _Conversations()
    sessions = _Sessions([keeper, stale])
    container = _Container(sessions, conversations, _Bridge())

    asyncio.run(_absorb_duplicates(container, keeper))

    assert conversations.calls == [(stale.id, keeper.id)]
    assert sessions.deleted == [stale.id]


def test_a_first_time_link_merges_nothing() -> None:
    # The overwhelmingly common case, and the one that must not touch anything.
    keeper = _session("+971501234567")
    conversations = _Conversations()
    sessions = _Sessions([keeper])
    container = _Container(sessions, conversations, _Bridge())

    asyncio.run(_absorb_duplicates(container, keeper))

    assert conversations.calls == []
    assert sessions.deleted == []


def test_a_different_number_in_the_same_workspace_is_left_alone() -> None:
    # Connecting a second, genuinely different number is the feature working,
    # not a duplicate to clean up.
    keeper, other = _session("+971501234567"), _session("+971509999999")
    conversations = _Conversations()
    sessions = _Sessions([keeper, other])
    container = _Container(sessions, conversations, _Bridge())

    asyncio.run(_absorb_duplicates(container, keeper))

    assert conversations.calls == []
    assert sessions.deleted == []


def test_a_session_that_linked_without_a_number_merges_nothing() -> None:
    # Defensive: an event with a blank phone number must not match every other
    # blank-numbered row and collapse the workspace into one session.
    blank = WhatsAppWebSession(tenant_id=TENANT)
    other = WhatsAppWebSession(tenant_id=TENANT)
    sessions = _Sessions([blank, other])
    conversations = _Conversations()
    container = _Container(sessions, conversations, _Bridge())

    asyncio.run(_absorb_duplicates(container, blank))

    assert conversations.calls == []
    assert sessions.deleted == []
