"""The streaming chat endpoint must actually stream an answer for the
ordinary case: a plain (non-booking) assistant, answering a message the input
guardrail does not flag.

This is a regression test for a real production bug, not a hypothetical one.
`ask_stream` used to compute `history_text` and `repeat_count` inside the
`if bot.assistant.appointments_enabled:` block, *after* that block's own
`return` — unreachable when the condition was true, and skipped entirely when
it was false. Either way, the two names were never assigned on any code path
that could actually run, and `event_generator()` referenced both while
building the prompt for the very first token. Python raised `UnboundLocalError`
there, deep inside an already-open SSE stream, after the harmless `citations`
event had already gone out — so the failure was invisible at the HTTP layer
and looked, from the browser, like the assistant had simply stopped answering.

It reproduced for the single most common case: an ordinary assistant with no
appointments feature, given an ordinary message that passes the input
guardrail. The one path that DID work — a message the guardrail blocks — never
touches either variable, which is exactly why this was so easy to miss by
hand-testing: "try a normal message" and "try a flagged one" give different
answers to "does this work at all".

Exercised through a real TestClient and a real running `ask_stream`, with only
the database and the model faked — a source-level check would not have caught
this, since the broken code was syntactically valid and every name it
referenced existed *somewhere* in the file.
"""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager

import pytest
from fastapi.testclient import TestClient
from src.application.ports.services import LLMResult
from src.config.container import get_container
from src.domain.chat.entities import ChatSession, Message, MessageRole
from src.domain.chatbot.entities import Chatbot
from src.domain.shared.identifiers import SessionId, TenantId
from src.domain.tenant.entities import Tenant
from src.interfaces.api.app import create_app
from src.interfaces.api.deps import Principal, container_dep, current_principal

TENANT_ID = TenantId(uuid.uuid4())


class FakeChatbots:
    def __init__(self, bot: Chatbot) -> None:
        self._bot = bot

    async def get(self, tenant_id, chatbot_id):  # type: ignore[no-untyped-def]
        return self._bot if chatbot_id == self._bot.id else None


class FakeChats:
    def __init__(self, session: ChatSession) -> None:
        self._session = session
        self.added: list[Message] = []

    async def get_session(self, tenant_id, session_id):  # type: ignore[no-untyped-def]
        return self._session if session_id == self._session.id else None

    async def list_messages(self, tenant_id, session_id, **kwargs):  # type: ignore[no-untyped-def]
        return list(self.added)

    async def add_message(self, message: Message) -> None:
        self.added.append(message)


class FakeTenants:
    async def get(self, tenant_id):  # type: ignore[no-untyped-def]
        return Tenant(name="Test", slug="test", id=tenant_id, daily_token_quota=200_000)


class FakeUsage:
    async def tokens_used_today(self, tenant_id) -> int:  # type: ignore[no-untyped-def]
        return 0

    async def add_tokens(self, tenant_id, tokens) -> None:  # type: ignore[no-untyped-def]
        return None


class FakeChunks:
    """An empty knowledge base — no citations. The bug under test has nothing
    to do with retrieval, so the simplest legitimate result is the right one."""

    async def search(self, **kwargs):  # type: ignore[no-untyped-def]
        return []


class FakeRequestLogs:
    async def add(self, log: object) -> None:
        return None


class FakeEmbedder:
    async def embed_query(self, text: str) -> list[float]:
        return [0.0] * 8


class FakeUow:
    def __init__(self, bot: Chatbot, session: ChatSession) -> None:
        self.chatbots = FakeChatbots(bot)
        self.chats = FakeChats(session)
        self.tenants = FakeTenants()
        self.usage = FakeUsage()
        self.chunks = FakeChunks()
        self.request_logs = FakeRequestLogs()
        self.scoped_to: TenantId | None = None

    async def __aenter__(self) -> FakeUow:
        return self

    async def __aexit__(self, *args: object) -> None:
        return None

    def set_tenant_scope(self, tenant_id) -> None:  # type: ignore[no-untyped-def]
        self.scoped_to = tenant_id

    async def commit(self) -> None:
        return None


class FakeStreamingLLM:
    """Streams a canned answer token by token, the way `container.llm.stream`
    does in production."""

    name = "fake"

    def __init__(self, tokens: list[str]) -> None:
        self._tokens = tokens

    async def generate(self, system: str, user: str) -> LLMResult:  # pragma: no cover - unused
        return LLMResult(text="".join(self._tokens), tokens_used=1, provider="fake", model="fake")

    async def stream(self, system, user, on_provider=None):  # type: ignore[no-untyped-def]
        if on_provider is not None:
            on_provider("fake")
        for token in self._tokens:
            yield token


@pytest.fixture
def streaming_client():  # type: ignore[no-untyped-def]
    bot = Chatbot(tenant_id=TENANT_ID, name="Plain Assistant")  # appointments off by default
    session = ChatSession(
        tenant_id=TENANT_ID, chatbot_id=bot.id, id=SessionId(uuid.uuid4())
    )
    uow = FakeUow(bot, session)

    container = get_container()
    container.llm = FakeStreamingLLM(["Hel", "lo", " there", "!"])  # type: ignore[assignment]
    container.embedder = FakeEmbedder()  # type: ignore[assignment]

    @asynccontextmanager
    async def fake_uow():
        yield uow

    container.unit_of_work = fake_uow  # type: ignore[assignment]

    app = create_app()
    app.dependency_overrides[container_dep] = lambda: container
    app.dependency_overrides[current_principal] = lambda: Principal(
        tenant_id=TENANT_ID, user_id=None, role="owner"
    )
    with TestClient(app) as client:
        yield client, session, uow


def _events(client: TestClient, session_id) -> list[tuple[str, str]]:  # type: ignore[no-untyped-def]
    events: list[tuple[str, str]] = []
    with client.stream(
        "POST",
        f"/api/v1/sessions/{session_id}/stream",
        json={"message": "What are your hours?"},
    ) as response:
        assert response.status_code == 200, response.read()
        event, data = None, None
        for line in response.iter_lines():
            if line.startswith("event:"):
                event = line[len("event:") :].strip()
            elif line.startswith("data:"):
                # Only the single space the SSE wire format puts after the
                # colon is not part of the payload — a naive .strip() would
                # also eat meaningful leading/trailing spaces inside a token
                # (" there" becoming "there"), silently corrupting the answer.
                raw = line[len("data:") :]
                data = raw[1:] if raw.startswith(" ") else raw
            elif line == "" and event is not None:
                events.append((event, data or ""))
                event, data = None, None
    return events


class TestAPlainAssistantActuallyStreamsAnAnswer:
    def test_token_events_arrive_and_spell_out_the_answer(self, streaming_client) -> None:  # type: ignore[no-untyped-def]
        client, session, _uow = streaming_client

        events = _events(client, session.id)

        tokens = [data for kind, data in events if kind == "token"]
        assert tokens, (
            "no token events arrived — this is exactly the UnboundLocalError "
            "regression: the stream opens, sends citations, then dies silently"
        )
        assert "".join(tokens) == "Hello there!"

    def test_the_stream_reaches_a_done_event(self, streaming_client) -> None:  # type: ignore[no-untyped-def]
        client, session, _uow = streaming_client

        events = _events(client, session.id)

        assert any(kind == "done" for kind, _ in events), (
            "the stream never completed — the client is left waiting forever, "
            "exactly like the reported 'assistant never answers' symptom"
        )

    def test_no_error_event_is_emitted(self, streaming_client) -> None:  # type: ignore[no-untyped-def]
        client, session, _uow = streaming_client

        events = _events(client, session.id)

        errors = [data for kind, data in events if kind == "error"]
        assert errors == [], f"stream reported an error: {errors}"

    def test_the_users_message_is_actually_persisted(self, streaming_client) -> None:  # type: ignore[no-untyped-def]
        client, session, uow = streaming_client

        _events(client, session.id)

        stored = [m for m in uow.chats.added if m.role == MessageRole.USER]
        assert len(stored) == 1
        assert stored[0].content == "What are your hours?"

    def test_a_second_turn_sees_the_first_as_history(self, streaming_client) -> None:  # type: ignore[no-untyped-def]
        # Proves `history_text` is now real, not just non-crashing: without it,
        # every turn is generated with no memory of the conversation, and the
        # assistant re-asks things the visitor already answered.
        client, session, uow = streaming_client

        _events(client, session.id)
        uow.chats.added.append(
            Message(
                session_id=session.id,
                tenant_id=TENANT_ID,
                role=MessageRole.ASSISTANT,
                content="We're open 9 to 6.",
            )
        )
        events = _events(client, session.id)

        assert [d for k, d in events if k == "token"], "the second turn must answer too"
        user_turns = [m for m in uow.chats.added if m.role == MessageRole.USER]
        assert len(user_turns) == 2
