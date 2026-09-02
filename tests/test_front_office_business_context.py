"""AskFrontOffice must load the assistant's own Conversational Flow and hand
it to the agent — the fix for a booking-enabled assistant answering as a
generic template on every channel that runs through this use case, because
nothing here ever fetched the chatbot row at all.

Hermetic: a minimal fake unit of work, no database, no network.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest
from src.application.use_cases.front_office import AskFrontOffice
from src.domain.chat.entities import ChatSession
from src.domain.chatbot.entities import Chatbot
from src.domain.shared.errors import NotFoundError
from src.domain.shared.identifiers import ChatbotId, SessionId, TenantId, new_id

TENANT = TenantId(new_id())


@dataclass
class _Tenant:
    daily_token_quota: int = 200_000


@dataclass
class _AgentResult:
    answer: str
    trace: object


@dataclass
class _Trace:
    tokens_used: int = 5
    provider: str = "fake"
    num_steps: int = 1
    stop_reason: str = "final"

    def tools_used(self) -> list[str]:
        return []


class _SpyAgent:
    """Records the exact call it received; returns a canned answer."""

    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def run(  # type: ignore[no-untyped-def]
        self, ctx, message, *, history="", tenant_prompt="", response_language=""
    ):
        self.calls.append(
            {
                "ctx": ctx,
                "message": message,
                "history": history,
                "tenant_prompt": tenant_prompt,
                "response_language": response_language,
            }
        )
        return _AgentResult(answer="Sure, happy to help.", trace=_Trace())


class _FakeUow:
    def __init__(self, bot: Chatbot, session: ChatSession) -> None:
        self.chatbots = _FakeChatbots(bot)
        self.chats = _FakeChats(session)
        self.tenants = _FakeTenants()
        self.usage = _FakeUsage()
        self.scoped_to: TenantId | None = None
        self.events: list = []

    async def __aenter__(self) -> _FakeUow:
        return self

    async def __aexit__(self, *args: object) -> None:
        return None

    def set_tenant_scope(self, tenant_id) -> None:  # type: ignore[no-untyped-def]
        self.scoped_to = tenant_id

    async def commit(self) -> None:
        return None

    def collect_event(self, event: object) -> None:
        self.events.append(event)


class _FakeChatbots:
    def __init__(self, bot: Chatbot) -> None:
        self._bot = bot

    async def get(self, tenant_id, chatbot_id):  # type: ignore[no-untyped-def]
        return self._bot if chatbot_id == self._bot.id else None


class _FakeChats:
    def __init__(self, session: ChatSession) -> None:
        self._session = session
        self.added: list = []

    async def get_session(self, tenant_id, session_id):  # type: ignore[no-untyped-def]
        return self._session if session_id == self._session.id else None

    async def list_messages(self, tenant_id, session_id, **kwargs):  # type: ignore[no-untyped-def]
        return []

    async def add_message(self, message) -> None:  # type: ignore[no-untyped-def]
        self.added.append(message)


class _FakeTenants:
    async def get(self, tenant_id):  # type: ignore[no-untyped-def]
        return _Tenant()


class _FakeUsage:
    async def tokens_used_today(self, tenant_id) -> int:  # type: ignore[no-untyped-def]
        return 0

    async def add_tokens(self, tenant_id, tokens) -> None:  # type: ignore[no-untyped-def]
        return None


def _bot(system_prompt: str) -> Chatbot:
    return Chatbot(tenant_id=TENANT, name="Reception", system_prompt=system_prompt)


@pytest.fixture
def world():  # type: ignore[no-untyped-def]
    bot = _bot("You are Maya, the receptionist for Bright Smile Dental.")
    session = ChatSession(tenant_id=TENANT, chatbot_id=bot.id, id=SessionId(new_id()))
    uow = _FakeUow(bot, session)
    agent = _SpyAgent()
    return uow, agent, bot, session


class TestTheAssistantsOwnPromptReachesTheAgent:
    async def test_the_chatbots_system_prompt_is_passed_through(self, world) -> None:  # type: ignore[no-untyped-def]
        uow, agent, bot, session = world
        use_case = AskFrontOffice(uow, agent)

        await use_case.execute(TENANT, session.id, message="who are you?")

        assert agent.calls[0]["tenant_prompt"] == bot.system_prompt

    async def test_an_explicit_chatbot_id_override_is_the_one_whose_prompt_is_used(
        self, world
    ) -> None:  # type: ignore[no-untyped-def]
        # AskFrontOffice accepts an explicit chatbot_id that can differ from the
        # session's own — the prompt loaded must follow THAT assistant, not
        # whichever one the session happened to start under.
        uow, agent, bot, session = world
        use_case = AskFrontOffice(uow, agent)

        await use_case.execute(
            TENANT, session.id, message="hi", chatbot_id=bot.id
        )

        assert agent.calls[0]["tenant_prompt"] == bot.system_prompt

    async def test_a_missing_assistant_raises_rather_than_answering_blind(
        self, world
    ) -> None:  # type: ignore[no-untyped-def]
        uow, agent, bot, session = world
        use_case = AskFrontOffice(uow, agent)

        with pytest.raises(NotFoundError):
            await use_case.execute(
                TENANT, session.id, message="hi", chatbot_id=ChatbotId(new_id())
            )


class TestTheAssistantsLanguagePolicyReachesTheAgent:
    async def test_the_response_language_is_passed_through(self, world) -> None:  # type: ignore[no-untyped-def]
        uow, agent, bot, session = world
        bot.assistant.response_language = "Hindi"
        use_case = AskFrontOffice(uow, agent)

        await use_case.execute(TENANT, session.id, message="who are you?")

        assert agent.calls[0]["response_language"] == "Hindi"
