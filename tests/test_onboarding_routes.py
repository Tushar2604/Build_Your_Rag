"""The staged shell's HTTP surface, exercised in process.

Fakes stand in for Postgres, same as `test_assistant_routes.py`. What these
pin is the contract the sidebar reads: one request answers how far the
workspace has got, what the next action is, and what this person has already
closed — and a preference write comes back with the whole recomputed state so
the client never has to follow it with a GET.
"""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager

import pytest
from fastapi.testclient import TestClient
from src.config.container import get_container
from src.domain.onboarding.entities import Milestones, OnboardingPrefs
from src.domain.shared.identifiers import TenantId, UserId
from src.interfaces.api.app import create_app
from src.interfaces.api.deps import Principal, container_dep, current_principal

TENANT_ID = TenantId(uuid.uuid4())
USER_ID = UserId(uuid.uuid4())


class FakeOnboardingRepo:
    def __init__(self, milestones: Milestones) -> None:
        self._milestones = milestones
        self.prefs: OnboardingPrefs | None = None

    async def milestones(self, tenant_id: TenantId) -> Milestones:
        assert tenant_id == TENANT_ID
        return self._milestones

    async def get_prefs(self, tenant_id: TenantId, user_id: UserId) -> OnboardingPrefs | None:
        return self.prefs

    async def save_prefs(self, prefs: OnboardingPrefs) -> None:
        self.prefs = prefs


class FakeSchedulingRepo:
    """No locations, services, resources or hours — booking is not set up."""

    async def list_for_tenant(self, tenant_id: TenantId) -> list:
        return []

    async def eligibility_for(self, tenant_id: TenantId, service_id) -> list:
        return []

    async def list_rules(self, tenant_id: TenantId, owner_id) -> list:
        return []


class FakeUnitOfWork:
    def __init__(self, onboarding: FakeOnboardingRepo) -> None:
        self.onboarding = onboarding
        scheduling = FakeSchedulingRepo()
        self.locations = scheduling
        self.services = scheduling
        self.resources = scheduling
        self.availability = scheduling
        self.documents = FakeSchedulingRepo()
        self.committed = 0

    def set_tenant_scope(self, tenant_id: TenantId) -> None:
        self.scope = tenant_id

    async def commit(self) -> None:
        self.committed += 1


def _api(milestones: Milestones):
    repo = FakeOnboardingRepo(milestones)
    container = get_container()

    @asynccontextmanager
    async def fake_uow():
        yield FakeUnitOfWork(repo)

    container.unit_of_work = fake_uow  # type: ignore[assignment]

    app = create_app()
    app.dependency_overrides[container_dep] = lambda: container
    app.dependency_overrides[current_principal] = lambda: Principal(
        tenant_id=TENANT_ID, user_id=USER_ID, role="owner"
    )
    return TestClient(app), repo


@pytest.fixture
def new_workspace():
    client, repo = _api(Milestones())
    with client:
        yield client, repo


@pytest.fixture
def live_workspace():
    client, repo = _api(Milestones(assistant_configured=True, assistant_live=True))
    with client:
        yield client, repo


class TestReadingState:
    def test_a_new_workspace_is_told_to_build_an_assistant(self, new_workspace) -> None:
        client, _ = new_workspace
        body = client.get("/api/v1/onboarding/state").json()

        assert body["stage"] == "build"
        assert body["next_step"]["href"] == "/assistants"
        # Nothing dismissed, nothing celebrated: a person with no row yet gets
        # sensible defaults rather than a 404.
        assert body["dismissed"] == []
        assert body["nav_mode"] == "guided"

    def test_a_live_workspace_is_at_operate(self, live_workspace) -> None:
        client, _ = live_workspace
        body = client.get("/api/v1/onboarding/state").json()

        assert body["stage"] == "operate"
        assert body["milestones"]["assistant_live"] is True

    def test_booking_readiness_is_folded_into_the_milestones(self, live_workspace) -> None:
        """The scheduling fakes are empty, so booking is genuinely not ready —
        and the next step for a live workspace is therefore to set it up."""
        client, _ = live_workspace
        body = client.get("/api/v1/onboarding/state").json()

        assert body["milestones"]["appointments_ready"] is False
        assert body["next_step"]["href"] == "/appointments/services"


class TestWritingPreferences:
    def test_a_dismissal_is_persisted_and_echoed_back(self, new_workspace) -> None:
        client, repo = new_workspace
        body = client.patch("/api/v1/onboarding/state", json={"dismiss": "welcome"}).json()

        assert body["dismissed"] == ["welcome"]
        assert repo.prefs is not None
        assert repo.prefs.dismissed == ["welcome"]

    def test_dismissing_twice_does_not_duplicate(self, new_workspace) -> None:
        client, _ = new_workspace
        client.patch("/api/v1/onboarding/state", json={"dismiss": "welcome"})
        body = client.patch("/api/v1/onboarding/state", json={"dismiss": "welcome"}).json()

        assert body["dismissed"] == ["welcome"]

    def test_a_write_returns_the_whole_state(self, new_workspace) -> None:
        """So a client that dismisses a card never needs a follow-up GET."""
        client, _ = new_workspace
        body = client.patch("/api/v1/onboarding/state", json={"dismiss": "welcome"}).json()

        assert body["stage"] == "build"
        assert body["next_step"]["cta"] == "Create assistant"

    def test_showing_all_features_is_remembered(self, new_workspace) -> None:
        client, _ = new_workspace
        body = client.patch("/api/v1/onboarding/state", json={"nav_mode": "full"}).json()

        assert body["nav_mode"] == "full"

    def test_an_unknown_nav_mode_is_rejected(self, new_workspace) -> None:
        client, _ = new_workspace
        assert client.patch("/api/v1/onboarding/state", json={"nav_mode": "wide"}).status_code == 422

    def test_reset_restores_the_guidance_without_touching_the_menu(self, new_workspace) -> None:
        """"Replay the walkthrough" must not silently re-hide someone's nav."""
        client, _ = new_workspace
        client.patch("/api/v1/onboarding/state", json={"nav_mode": "full"})
        client.patch("/api/v1/onboarding/state", json={"dismiss": "checklist"})
        client.patch("/api/v1/onboarding/state", json={"complete_tour": "assistants"})

        body = client.patch("/api/v1/onboarding/state", json={"reset": True}).json()

        assert body["dismissed"] == []
        assert body["tours_completed"] == []
        assert body["nav_mode"] == "full"

    def test_celebrating_a_stage_stops_it_being_pending(self, live_workspace) -> None:
        client, _ = live_workspace
        body = client.patch(
            "/api/v1/onboarding/state", json={"celebrate_stage": "operate"}
        ).json()

        assert body["celebrated_stages"] == ["operate"]
