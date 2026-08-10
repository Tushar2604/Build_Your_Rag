"""The assistant builder's HTTP surface, exercised in process.

An in-memory unit of work stands in for Postgres. That is enough to test what
these routes actually decide — what gets persisted, what is rejected, and what
the browser is told — without a database, which is what lets these run in CI on
a machine with nothing installed.
"""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from src.application.ports.repositories import OAuthConnection
from src.application.ports.services import LLMResult
from src.config.container import get_container
from src.domain.chatbot.entities import Chatbot
from src.domain.document.entities import Document, IngestionStatus
from src.domain.shared.identifiers import ChatbotId, DocumentId, TenantId
from src.infrastructure.oauth.providers import OAuthBroker
from src.interfaces.api.app import create_app
from src.interfaces.api.deps import Principal, container_dep, current_principal

TENANT_ID = TenantId(uuid.uuid4())


class FakeChatbotRepo:
    def __init__(self) -> None:
        self.items: dict[uuid.UUID, Chatbot] = {}

    async def add(self, bot: Chatbot) -> None:
        self.items[bot.id] = bot

    async def get(self, tenant_id: TenantId, chatbot_id: ChatbotId) -> Chatbot | None:
        bot = self.items.get(chatbot_id)
        return bot if bot and bot.tenant_id == tenant_id else None

    async def update(self, bot: Chatbot) -> None:
        self.items[bot.id] = bot

    async def list_for_tenant(self, tenant_id: TenantId) -> list[Chatbot]:
        return [b for b in self.items.values() if b.tenant_id == tenant_id]


class FakeDocumentRepo:
    def __init__(self) -> None:
        self.items: list[Document] = []

    async def list_for_tenant(self, tenant_id: TenantId) -> list[Document]:
        return [d for d in self.items if d.tenant_id == tenant_id]

    async def list_resumable(self) -> list[Document]:
        # Called by the startup resume sweep, which runs for every TestClient.
        return []


class FakeUnitOfWork:
    def __init__(self, chatbots: FakeChatbotRepo, documents: FakeDocumentRepo) -> None:
        self.chatbots = chatbots
        self.documents = documents
        self.committed = 0

    def set_tenant_scope(self, tenant_id: TenantId) -> None:
        self.scope = tenant_id

    async def commit(self) -> None:
        self.committed += 1


class FakeLLM:
    name = "fake"

    def __init__(self, text: str) -> None:
        self.text = text

    async def generate(self, system: str, user: str) -> LLMResult:
        return LLMResult(text=self.text, tokens_used=1, provider="fake", model="fake")


GENERATED = """{
  "name": "Google India Hiring Assistant",
  "direction": "outgoing",
  "welcome_message": "Hi [user_name], this is the Google India Hiring Team.",
  "sections": [
    {"title": "Identity & Purpose", "body": "You are a recruiting assistant."},
    {"title": "Facts", "body": "- Google India hires in Bengaluru and Hyderabad."},
    {"title": "Actions & Limits", "body": "- CAN: confirm candidate interest."},
    {"title": "Flow: candidate qualification", "body": "1. Confirm the role."},
    {"title": "Scope & Redirects", "body": "Stay focused on hiring."}
  ]
}"""


@pytest.fixture
def api():
    """A TestClient wired to fakes, plus the repos so tests can inspect state."""
    chatbots, documents = FakeChatbotRepo(), FakeDocumentRepo()
    container = get_container()
    container.llm = FakeLLM(GENERATED)  # type: ignore[assignment]

    @asynccontextmanager
    async def fake_uow():
        yield FakeUnitOfWork(chatbots, documents)

    container.unit_of_work = fake_uow  # type: ignore[assignment]

    app = create_app()
    app.dependency_overrides[container_dep] = lambda: container
    app.dependency_overrides[current_principal] = lambda: Principal(
        tenant_id=TENANT_ID, user_id=None, role="owner"
    )
    with TestClient(app) as client:
        yield client, chatbots, documents


def _generate(client: TestClient) -> dict:
    response = client.post(
        "/api/v1/chatbots/generate",
        json={"description": "call candidates who applied to Google India"},
    )
    assert response.status_code == 201, response.text
    return response.json()


class TestGenerate:
    def test_a_description_produces_a_saved_assistant(self, api) -> None:
        client, chatbots, _ = api
        body = _generate(client)

        assert body["name"] == "Google India Hiring Assistant"
        assert body["ai_generated"] is True
        assert body["assistant"]["welcome_message"].startswith("Hi [user_name]")
        # Saved, not just returned — the builder opens it next.
        assert len(chatbots.items) == 1

    def test_the_flow_is_specific_to_the_description(self, api) -> None:
        client, _, _ = api
        titles = [s["title"] for s in _generate(client)["flow_sections"]]

        assert "Flow: candidate qualification" in titles
        assert titles[0] == "Identity & Purpose"
        assert titles[-1] == "Guardrails"

    def test_the_composed_prompt_is_what_the_model_will_receive(self, api) -> None:
        client, _, _ = api
        body = _generate(client)

        assert "## Identity & Purpose" in body["system_prompt"]
        assert "You are a recruiting assistant." in body["system_prompt"]

    def test_a_too_short_description_is_rejected(self, api) -> None:
        client, _, _ = api
        response = client.post("/api/v1/chatbots/generate", json={"description": "hi"})
        assert response.status_code == 422

    def test_regenerating_keeps_the_name_and_replaces_the_flow(self, api) -> None:
        client, chatbots, _ = api
        created = _generate(client)
        bot = chatbots.items[uuid.UUID(created["id"])]
        bot.name = "Renamed By Owner"

        response = client.post(
            f"/api/v1/chatbots/{created['id']}/flow/generate",
            json={"description": "call candidates about senior backend roles"},
        )
        assert response.status_code == 200, response.text
        assert response.json()["name"] == "Renamed By Owner"
        assert "Flow: candidate qualification" in [
            s["title"] for s in response.json()["flow_sections"]
        ]


class TestAssistantSettings:
    def test_settings_round_trip_through_a_patch(self, api) -> None:
        client, _, _ = api
        created = _generate(client)

        response = client.patch(
            f"/api/v1/chatbots/{created['id']}",
            json={
                "assistant": {
                    "direction": "incoming",
                    "languages": ["Hindi", "English (India)"],
                    "tts_voice": "ElevenLabs - Rachel",
                    "llm_model": "gemini-2.5-flash",
                    "stt_model": "Deepgram",
                    "welcome_message": "Namaste!",
                    "welcome_dynamic": False,
                    "welcome_interruptible": True,
                }
            },
        )
        assert response.status_code == 200, response.text
        assistant = response.json()["assistant"]
        assert assistant["direction"] == "incoming"
        assert assistant["languages"] == ["Hindi", "English (India)"]
        assert assistant["welcome_dynamic"] is False

    def test_the_options_endpoint_offers_only_accepted_values(self, api) -> None:
        client, _, _ = api
        options = client.get("/api/v1/chatbots/options").json()

        assert "English (India)" in options["languages"]
        assert {u["id"] for u in options["use_cases"]} >= {"lead_generation", "support"}

    def test_prompt_and_flow_together_are_rejected(self, api) -> None:
        # They are two views of the same thing; letting one win silently would
        # lose the owner's edits.
        client, _, _ = api
        created = _generate(client)
        response = client.patch(
            f"/api/v1/chatbots/{created['id']}",
            json={"system_prompt": "hi", "flow_sections": [{"title": "T", "body": "B"}]},
        )
        assert response.status_code == 400


class TestKnowledgeBase:
    def _add_docs(self, documents: FakeDocumentRepo) -> list[Document]:
        docs = [
            Document(
                tenant_id=TENANT_ID,
                filename=name,
                content_type="application/pdf",
                size_bytes=10,
                storage_key=f"k/{name}",
                checksum="deadbeef",
                status=status,
                chunk_count=3 if status is IngestionStatus.READY else 0,
            )
            for name, status in [
                ("handbook.pdf", IngestionStatus.READY),
                ("pricing.pdf", IngestionStatus.READY),
                ("draft.pdf", IngestionStatus.PARSING),
            ]
        ]
        documents.items.extend(docs)
        return docs

    def test_an_assistant_starts_searching_everything(self, api) -> None:
        client, _, documents = api
        self._add_docs(documents)
        created = _generate(client)

        body = client.get(f"/api/v1/chatbots/{created['id']}/knowledge").json()
        assert body["scope_is_all"] is True
        assert body["attached_count"] == 0
        assert body["ready_count"] == 2  # the parsing one is not ready
        assert len(body["documents"]) == 3

    def test_attaching_documents_narrows_the_scope(self, api) -> None:
        client, chatbots, documents = api
        docs = self._add_docs(documents)
        created = _generate(client)

        body = client.put(
            f"/api/v1/chatbots/{created['id']}/knowledge",
            json={"document_ids": [str(docs[0].id)]},
        ).json()

        assert body["scope_is_all"] is False
        assert body["attached_count"] == 1
        assert [d["attached"] for d in body["documents"]] == [True, False, False]
        # And it actually reached the aggregate that drives retrieval.
        bot = chatbots.items[uuid.UUID(created["id"])]
        assert bot.document_filter() == [DocumentId(docs[0].id)]

    def test_documents_from_another_tenant_are_dropped(self, api) -> None:
        # A dangling id would sit in the allowlist forever and quietly narrow
        # retrieval to nothing.
        client, chatbots, documents = api
        self._add_docs(documents)
        created = _generate(client)

        body = client.put(
            f"/api/v1/chatbots/{created['id']}/knowledge",
            json={"document_ids": [str(uuid.uuid4())]},
        ).json()

        assert body["attached_count"] == 0
        assert chatbots.items[uuid.UUID(created["id"])].allowed_document_ids == []

    def test_clearing_the_selection_searches_everything_again(self, api) -> None:
        client, _, documents = api
        docs = self._add_docs(documents)
        created = _generate(client)

        client.put(
            f"/api/v1/chatbots/{created['id']}/knowledge",
            json={"document_ids": [str(docs[0].id)]},
        )
        body = client.put(
            f"/api/v1/chatbots/{created['id']}/knowledge", json={"document_ids": []}
        ).json()

        assert body["scope_is_all"] is True

    def test_an_unknown_assistant_is_a_404(self, api) -> None:
        client, _, _ = api
        assert (
            client.get(f"/api/v1/chatbots/{uuid.uuid4()}/knowledge").status_code == 404
        )


class FakeTenantIntegrationRepo:
    async def list_for_tenant(self, tenant_id: TenantId) -> list:
        return []


class FakeOAuthRepo:
    def __init__(self) -> None:
        self.items: list[OAuthConnection] = []

    async def list_for_tenant(self, tenant_id: TenantId) -> list[OAuthConnection]:
        return [c for c in self.items if c.tenant_id == tenant_id]

    async def get(self, tenant_id: TenantId, provider: str) -> OAuthConnection | None:
        return next(
            (c for c in self.items if c.tenant_id == tenant_id and c.provider == provider),
            None,
        )

    async def upsert(self, connection: OAuthConnection) -> None:
        await self.delete(connection.tenant_id, connection.provider)
        self.items.append(connection)

    async def delete(self, tenant_id: TenantId, provider: str) -> None:
        self.items = [
            c for c in self.items if not (c.tenant_id == tenant_id and c.provider == provider)
        ]


@pytest.fixture
def catalogue_api(monkeypatch):
    """The integrations catalogue, with Google's OAuth app configured."""
    oauth_repo = FakeOAuthRepo()
    documents = FakeDocumentRepo()
    container = get_container()

    # A configured Google app — otherwise every OAuth card reports "not
    # configured" and the interesting branches never run.
    monkeypatch.setattr(container.settings, "google_oauth_client_id", "id", raising=False)
    monkeypatch.setattr(container.settings, "google_oauth_client_secret", "secret", raising=False)
    container.oauth = OAuthBroker(container.settings)

    class Uow(FakeUnitOfWork):
        def __init__(self) -> None:
            super().__init__(FakeChatbotRepo(), documents)
            self.oauth_connections = oauth_repo
            self.tenant_integrations = FakeTenantIntegrationRepo()

    @asynccontextmanager
    async def fake_uow():
        yield Uow()

    container.unit_of_work = fake_uow  # type: ignore[assignment]

    app = create_app()
    app.dependency_overrides[container_dep] = lambda: container
    app.dependency_overrides[current_principal] = lambda: Principal(
        tenant_id=TENANT_ID, user_id=None, role="owner"
    )
    with TestClient(app) as client:
        yield client, oauth_repo


def _card(body: dict, integration_id: str) -> dict:
    return next(c for c in body["integrations"] if c["id"] == integration_id)


class TestIntegrationsCatalogue:
    def test_configured_oauth_integrations_are_connectable(self, catalogue_api) -> None:
        client, _ = catalogue_api
        body = client.get("/api/v1/integrations-catalogue").json()

        for provider in ("google_calendar", "google_sheets"):
            card = _card(body, provider)
            assert card["auth"] == "oauth"
            assert card["wired"] is True, f"{provider} should offer a Connect button"
            assert card["connected"] is False

    def test_an_unconfigured_oauth_integration_explains_itself(self, catalogue_api) -> None:
        # Rather than showing a Connect button that would 400 on click.
        client, _ = catalogue_api
        card = _card(client.get("/api/v1/integrations-catalogue").json(), "cal_com")

        assert card["wired"] is False
        assert card["unavailable_reason"]

    def test_a_consent_shows_up_as_connected_with_the_account(self, catalogue_api) -> None:
        client, oauth_repo = catalogue_api
        oauth_repo.items.append(
            OAuthConnection(
                tenant_id=TENANT_ID,
                provider="google_calendar",
                access_token="tok",
                expires_at=datetime.now(UTC) + timedelta(hours=1),
                account_label="ops@example.com",
            )
        )

        body = client.get("/api/v1/integrations-catalogue").json()
        card = _card(body, "google_calendar")
        assert card["connected"] is True
        assert card["config"]["account"] == "ops@example.com"
        assert body["connected_count"] == 1

    def test_disconnecting_an_oauth_integration_revokes_the_consent(self, catalogue_api) -> None:
        # It lives in oauth_connections; deleting the absent tenant_integrations
        # row would report success and disconnect nothing.
        client, oauth_repo = catalogue_api
        oauth_repo.items.append(
            OAuthConnection(
                tenant_id=TENANT_ID,
                provider="google_calendar",
                access_token="tok",
                expires_at=datetime.now(UTC) + timedelta(hours=1),
            )
        )

        assert client.delete("/api/v1/integrations-catalogue/google_calendar").status_code == 204
        assert oauth_repo.items == []
