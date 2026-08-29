"""Guard: one contact, one thread — whichever writer saw them first.

The reported symptom was `+919220910108` appearing three times in Candidates,
same name each time, with the conversation split between the copies.

`whatsapp_conversations` is unique on `(owner, phone_number)`, and the number
reached that column through four writers with four spellings. This covers the
personal-WhatsApp writer, which is the one the bridge drives on every inbound
message and therefore the one that would keep re-creating the split.
"""

from __future__ import annotations

import asyncio

from src.application.ports.repositories import WhatsAppConversation
from src.domain.shared.identifiers import ChatbotId, SessionId, TenantId, new_id
from src.interfaces.api.routers.whatsapp_web import _ensure_conversation

TENANT = TenantId(new_id())
OWNER = new_id()
BOT = ChatbotId(new_id())


class _Conversations:
    """A stand-in for the repository that matches the way the real one does:
    on the digits, not on the stored string."""

    def __init__(self, existing: list[WhatsAppConversation] | None = None) -> None:
        self.rows = list(existing or [])
        self.added: list[WhatsAppConversation] = []

    async def get(self, owner_id, phone_number):
        from src.domain.shared.phone import phone_digits

        wanted = phone_digits(phone_number)
        for row in self.rows:
            if row.whatsapp_channel_id != owner_id:
                continue
            if wanted and phone_digits(row.phone_number) == wanted:
                return row
            if not wanted and row.phone_number == phone_number:
                return row
        return None

    async def add(self, conversation) -> None:
        self.rows.append(conversation)
        self.added.append(conversation)


class _Chats:
    def __init__(self) -> None:
        self.sessions: list = []

    async def add_session(self, session) -> None:
        self.sessions.append(session)


class _Uow:
    def __init__(self, conversations: _Conversations) -> None:
        self.whatsapp_conversations = conversations
        self.chats = _Chats()


def _run(conversations: _Conversations, phone: str, name: str = ""):
    return asyncio.run(
        _ensure_conversation(_Uow(conversations), TENANT, BOT, OWNER, phone, name)
    )


def _existing(phone: str) -> WhatsAppConversation:
    return WhatsAppConversation(
        whatsapp_channel_id=OWNER,
        phone_number=phone,
        session_id=SessionId(new_id()),
        tenant_id=TENANT,
        display_name="Ahmed Khan",
    )


def test_a_new_contact_is_stored_in_one_canonical_shape() -> None:
    conversations = _Conversations()
    _run(conversations, "919220910108@s.whatsapp.net", "Ahmed Khan")
    assert conversations.added[0].phone_number == "+919220910108"


def test_the_same_person_arriving_differently_reuses_their_thread() -> None:
    # The bug, exactly: the history import says "+91 92209 10108" and the live
    # socket says "+919220910108", and the second one opened a second thread.
    existing = _existing("+91 92209 10108")
    conversations = _Conversations([existing])

    found = _run(conversations, "+919220910108")

    assert found is existing
    assert conversations.added == []


def test_a_campaign_recipient_who_replies_lands_on_the_campaign_thread() -> None:
    # The campaign wrote "+919220910108"; the reply arrives as a bare JID.
    existing = _existing("+919220910108")
    conversations = _Conversations([existing])

    assert _run(conversations, "919220910108") is existing


def test_a_different_number_still_gets_its_own_thread() -> None:
    conversations = _Conversations([_existing("+919220910108")])
    _run(conversations, "+919220910109", "Someone Else")
    assert len(conversations.added) == 1
    assert conversations.added[0].phone_number == "+919220910109"


def test_the_same_contact_on_a_second_connected_number_stays_separate() -> None:
    # Deliberately NOT deduplicated: two connected numbers that both talked to
    # this person are two real conversations, and the Candidates view groups
    # them rather than destroying one.
    other_owner = new_id()
    conversations = _Conversations([_existing("+919220910108")])

    asyncio.run(
        _ensure_conversation(_Uow(conversations), TENANT, BOT, other_owner, "+919220910108", "")
    )

    assert len(conversations.added) == 1
    assert conversations.added[0].whatsapp_channel_id == other_owner


def test_a_name_learned_later_fills_in_a_blank_one() -> None:
    existing = _existing("+919220910108")
    existing.display_name = ""
    conversations = _Conversations([existing])

    _run(conversations, "919220910108", "Ahmed Khan")

    assert existing.display_name == "Ahmed Khan"


def test_an_unparseable_key_still_finds_its_own_thread() -> None:
    # Without the exact-match fallback this thread would be re-created on every
    # inbound message, which is the same bug wearing a different hat.
    existing = _existing("unknown")
    conversations = _Conversations([existing])

    assert _run(conversations, "unknown") is existing
    assert conversations.added == []
