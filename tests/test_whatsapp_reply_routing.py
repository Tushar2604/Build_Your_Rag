"""Guard: a WhatsApp thread is answered by the assistant attached *now*.

The reported symptom was "I connect an agent to the number and nothing ever
replies", and there were three separate reasons for it — each of which is a
silent failure, because the reply runs in a background task after the bridge
has already had its 200.

  1. A thread is created at the first inbound message, stamped with whichever
     assistant was attached at that instant — usually none, because pairing
     comes before choosing. Answering read the *thread's* assistant, so picking
     one later changed nothing for any conversation already in the inbox.
  2. A chat session with no assistant could not even be written: the column was
     NOT NULL, so the whole bridge event 500'd and the message was dropped.
  3. Nothing distinguished "no assistant attached" from "generation blew up" in
     the logs, so neither end of the pipeline could say what had happened.

These cover the routing decision (1) at the use-case seam. The state-machine
half lives in tests/domain/test_whatsapp_web_session.py.
"""

from __future__ import annotations

import uuid

import pytest
from src.application.dtos import AskInput
from src.application.ports.services import LLMResult
from src.application.use_cases.ask_chatbot import AskChatbot
from src.domain.chat.entities import ChatSession
from src.domain.chatbot.entities import Chatbot
from src.domain.shared.errors import NotFoundError
from src.domain.shared.identifiers import ChatbotId, SessionId, TenantId, new_id
from src.domain.tenant.entities import Tenant

TENANT = TenantId(new_id())
OLD_BOT = ChatbotId(new_id())
NEW_BOT = ChatbotId(new_id())
SESSION = SessionId(new_id())


class _Chatbots:
    def __init__(self, known: dict[ChatbotId, Chatbot]) -> None:
        self.known = known
        self.asked_for: list[ChatbotId | None] = []

    async def get(self, tenant_id, chatbot_id):
        self.asked_for.append(chatbot_id)
        return self.known.get(chatbot_id)


class _Chats:
    def __init__(self, session: ChatSession | None) -> None:
        self.session = session
        self.added: list = []

    async def get_session(self, tenant_id, session_id):
        return self.session

    async def list_messages(self, tenant_id, session_id, **kwargs):
        return []

    async def add_message(self, message) -> None:
        self.added.append(message)


class _Chunks:
    async def search(self, **kwargs):
        return []


class _Usage:
    async def tokens_used_today(self, tenant_id) -> int:
        return 0

    async def add_tokens(self, tenant_id, tokens) -> None:
        pass


class _Tenants:
    async def get(self, tenant_id):
        return Tenant(id=TENANT, name="Acme", slug="acme")


class _RequestLogs:
    async def add(self, entry) -> None:
        pass


class _Uow:
    def __init__(self, chats: _Chats, chatbots: _Chatbots) -> None:
        self.chats = chats
        self.chatbots = chatbots
        self.chunks = _Chunks()
        self.usage = _Usage()
        self.tenants = _Tenants()
        self.request_logs = _RequestLogs()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc) -> None:
        return None

    def set_tenant_scope(self, tenant_id) -> None:
        pass

    def collect_event(self, event) -> None:
        pass

    async def commit(self) -> None:
        pass


class _Embedder:
    async def embed_query(self, text: str) -> list[float]:
        return [0.0, 1.0]


class _LLM:
    def __init__(self) -> None:
        self.system_prompts: list[str] = []

    async def generate(self, system: str, user: str) -> LLMResult:
        self.system_prompts.append(system)
        return LLMResult(
            text="Sure — sending that over.", tokens_used=7, provider="fake", model="fake"
        )


def _bot(chatbot_id: ChatbotId, name: str) -> Chatbot:
    bot = Chatbot(tenant_id=TENANT, name=name, id=chatbot_id)
    bot.set_raw_prompt(f"You are {name}.")
    return bot


def _run(session: ChatSession | None, known: dict[ChatbotId, Chatbot], data: AskInput):
    chats = _Chats(session)
    chatbots = _Chatbots(known)
    llm = _LLM()
    use_case = AskChatbot(_Uow(chats, chatbots), _Embedder(), llm)
    import asyncio

    result = asyncio.run(use_case.execute(TENANT, SESSION, data))
    return result, chatbots, llm


def test_the_override_wins_over_the_assistant_the_thread_was_opened_with() -> None:
    # The whole bug: the thread still points at whoever was attached when the
    # first message landed, and that is not who the user has chosen since.
    session = ChatSession(tenant_id=TENANT, chatbot_id=OLD_BOT, id=SESSION)
    known = {OLD_BOT: _bot(OLD_BOT, "Old"), NEW_BOT: _bot(NEW_BOT, "New")}

    _, chatbots, llm = _run(
        session, known, AskInput(message="hi", persist_user_message=False, chatbot_id=NEW_BOT)
    )

    assert chatbots.asked_for == [NEW_BOT]
    assert llm.system_prompts == ["You are New."]


def test_a_thread_with_no_assistant_can_still_be_answered_when_one_is_supplied() -> None:
    # Threads created before an assistant was attached carry chatbot_id=None.
    # They are the majority after a fresh link, and they must not be dead.
    session = ChatSession(tenant_id=TENANT, chatbot_id=None, id=SESSION)

    _, chatbots, llm = _run(
        session,
        {NEW_BOT: _bot(NEW_BOT, "New")},
        AskInput(message="hi", persist_user_message=False, chatbot_id=NEW_BOT),
    )

    assert chatbots.asked_for == [NEW_BOT]
    assert llm.system_prompts == ["You are New."]


def test_without_an_override_the_thread_s_own_assistant_answers() -> None:
    # The widget and hosted-chat paths pass no override and must be unaffected.
    session = ChatSession(tenant_id=TENANT, chatbot_id=OLD_BOT, id=SESSION)

    _, chatbots, llm = _run(
        session, {OLD_BOT: _bot(OLD_BOT, "Old")}, AskInput(message="hi", persist_user_message=False)
    )

    assert chatbots.asked_for == [OLD_BOT]
    assert llm.system_prompts == ["You are Old."]


def test_a_thread_with_no_assistant_and_no_override_is_refused_not_crashed() -> None:
    # Reached when a number has no assistant attached at all. It must raise the
    # domain's own not-found rather than blowing up on `get(tenant, None)`.
    session = ChatSession(tenant_id=TENANT, chatbot_id=None, id=SESSION)

    with pytest.raises(NotFoundError):
        _run(session, {}, AskInput(message="hi", persist_user_message=False))


def test_an_override_naming_a_deleted_assistant_is_refused() -> None:
    session = ChatSession(tenant_id=TENANT, chatbot_id=OLD_BOT, id=SESSION)

    with pytest.raises(NotFoundError):
        _run(
            session,
            {OLD_BOT: _bot(OLD_BOT, "Old")},
            AskInput(message="hi", persist_user_message=False, chatbot_id=uuid.uuid4()),
        )
