"""Enabling booking has to leave a workspace that can actually take a booking.

The reported symptom: an operator creates an assistant, turns Appointments on,
asks it for a time, and is told there is no availability — forever. Nothing is
broken; the workspace has no location, no service, no staff and no opening
hours, and the availability engine is correctly answering "nothing" about a
business that has told it nothing.

`EnsureBookingSetup` closes that gap on the one action that promises booking
works. These tests pin the two halves of the promise: it fills in what is
missing, and it never touches what the operator has already decided.
"""

from __future__ import annotations

from datetime import time

import pytest
from src.application.use_cases.booking_setup import (
    DEFAULT_OPEN_FROM,
    DEFAULT_OPEN_UNTIL,
    DEFAULT_OPEN_WEEKDAYS,
    EnsureBookingSetup,
)
from src.domain.scheduling.entities import (
    AvailabilityRule,
    Location,
    Resource,
    Service,
    ServiceResource,
)
from src.domain.shared.identifiers import TenantId, new_id
from src.domain.tenant.entities import Tenant

TENANT = TenantId(new_id())


class _World:
    """An in-memory workspace. A fake rather than a mock, so a seed that writes
    to the wrong tenant fails a test instead of passing one."""

    def __init__(self) -> None:
        self.tenant = Tenant(name="Bright Smile Dental", slug="bright-smile", id=TENANT)
        self.locations: list[Location] = []
        self.services: list[Service] = []
        self.resources: list[Resource] = []
        self.eligibility: list[ServiceResource] = []
        self.rules: list[AvailabilityRule] = []
        self.commits = 0

    def uow_factory(self) -> _FakeUow:
        return _FakeUow(self)


class _FakeUow:
    def __init__(self, world: _World) -> None:
        self._w = world
        self.tenants = _FakeTenants(world)
        self.locations = _FakeLocations(world)
        self.services = _FakeServices(world)
        self.resources = _FakeResources(world)
        self.availability = _FakeAvailability(world)
        self.scoped_to: TenantId | None = None

    async def __aenter__(self) -> _FakeUow:
        return self

    async def __aexit__(self, *args: object) -> None:
        return None

    def set_tenant_scope(self, tenant_id) -> None:  # type: ignore[no-untyped-def]
        self.scoped_to = tenant_id

    async def flush(self) -> None:
        return None

    async def commit(self) -> None:
        self._w.commits += 1


class _FakeTenants:
    def __init__(self, w: _World) -> None:
        self._w = w

    async def get(self, tenant_id):  # type: ignore[no-untyped-def]
        return self._w.tenant if tenant_id == self._w.tenant.id else None


class _FakeLocations:
    def __init__(self, w: _World) -> None:
        self._w = w

    async def add(self, location: Location) -> None:
        self._w.locations.append(location)

    async def list_for_tenant(self, tenant_id, *, active_only=False):  # type: ignore[no-untyped-def]
        return [loc for loc in self._w.locations if loc.tenant_id == tenant_id]


class _FakeServices:
    def __init__(self, w: _World) -> None:
        self._w = w

    async def add(self, service: Service) -> None:
        self._w.services.append(service)

    async def list_for_tenant(self, tenant_id, *, active_only=False):  # type: ignore[no-untyped-def]
        return [s for s in self._w.services if s.tenant_id == tenant_id]

    async def eligibility_for(self, tenant_id, service_id):  # type: ignore[no-untyped-def]
        return [
            link
            for link in self._w.eligibility
            if link.tenant_id == tenant_id and link.service_id == service_id
        ]

    async def set_eligibility(self, tenant_id, service_id, links):  # type: ignore[no-untyped-def]
        self._w.eligibility = [
            link
            for link in self._w.eligibility
            if not (link.tenant_id == tenant_id and link.service_id == service_id)
        ] + list(links)


class _FakeResources:
    def __init__(self, w: _World) -> None:
        self._w = w

    async def add(self, resource: Resource) -> None:
        self._w.resources.append(resource)

    async def list_for_tenant(self, tenant_id, **kwargs):  # type: ignore[no-untyped-def]
        return [r for r in self._w.resources if r.tenant_id == tenant_id]


class _FakeAvailability:
    def __init__(self, w: _World) -> None:
        self._w = w

    async def add_rule(self, rule: AvailabilityRule) -> None:
        self._w.rules.append(rule)

    async def list_rules(self, tenant_id, owner_id):  # type: ignore[no-untyped-def]
        return [
            r
            for r in self._w.rules
            if r.tenant_id == tenant_id and r.owner_id == owner_id
        ]


@pytest.fixture
def world() -> _World:
    return _World()


async def _seed(world: _World, *, timezone: str = "Asia/Dubai"):  # type: ignore[no-untyped-def]
    return await EnsureBookingSetup(world.uow_factory()).execute(
        TENANT, timezone=timezone
    )


class TestAnEmptyWorkspaceBecomesBookable:
    async def test_it_creates_everything_the_engine_needs(self, world: _World) -> None:
        report = await _seed(world)

        assert len(world.locations) == 1
        assert len(world.services) == 1
        assert len(world.resources) == 1
        assert len(world.eligibility) == 1
        assert world.rules, "a branch with no hours is closed, so nothing is bookable"
        assert report.changed

    async def test_the_hours_belong_to_the_location(self, world: _World) -> None:
        # `compute_slots` returns nothing at all when the *branch* has no rules;
        # a resource with none of its own simply inherits the branch's. Seeding
        # resource hours instead would look right and book nothing.
        await _seed(world)
        owner_kinds = {rule.owner_kind for rule in world.rules}
        assert owner_kinds == {"location"}
        assert {rule.owner_id for rule in world.rules} == {world.locations[0].id}

    async def test_it_opens_the_days_and_hours_it_says_it_does(
        self, world: _World
    ) -> None:
        await _seed(world)
        assert {r.weekday for r in world.rules} == set(DEFAULT_OPEN_WEEKDAYS)
        assert all(r.start_time == DEFAULT_OPEN_FROM for r in world.rules)
        assert all(r.end_time == DEFAULT_OPEN_UNTIL for r in world.rules)

    async def test_the_location_takes_the_configured_timezone(
        self, world: _World
    ) -> None:
        # It decides what "9 AM" means to the customer, so it is configuration
        # rather than a constant.
        await _seed(world, timezone="Asia/Kolkata")
        assert world.locations[0].timezone == "Asia/Kolkata"

    async def test_an_unusable_timezone_still_leaves_a_bookable_branch(
        self, world: _World
    ) -> None:
        # Wrong by an offset beats closed by every hour of the week.
        await _seed(world, timezone="Mars/Olympus_Mons")
        assert world.locations[0].timezone == "UTC"
        assert world.rules

    async def test_the_service_is_linked_to_the_staff_member(
        self, world: _World
    ) -> None:
        # A service nobody can perform has no slots, which is the readiness
        # blocker operators hit most often.
        await _seed(world)
        link = world.eligibility[0]
        assert link.service_id == world.services[0].id
        assert link.resource_id == world.resources[0].id
        assert link.required

    async def test_it_names_what_it_created(self, world: _World) -> None:
        # The operator has to be able to find these rows and recognise them.
        report = await _seed(world)
        assert len(report.created) == 5
        assert any("Opening hours" in line for line in report.created)


class TestItNeverOverwritesWhatTheOperatorSet:
    async def test_running_twice_changes_nothing_the_second_time(
        self, world: _World
    ) -> None:
        await _seed(world)
        before = (len(world.locations), len(world.services), len(world.resources), len(world.rules))

        report = await _seed(world)

        after = (len(world.locations), len(world.services), len(world.resources), len(world.rules))
        assert after == before
        assert not report.changed

    async def test_an_existing_location_is_used_rather_than_duplicated(
        self, world: _World
    ) -> None:
        existing = Location(tenant_id=TENANT, name="Marina Branch", timezone="Asia/Dubai")
        world.locations.append(existing)

        await _seed(world)

        assert [loc.name for loc in world.locations] == ["Marina Branch"]
        assert {r.owner_id for r in world.rules} == {existing.id}

    async def test_hours_the_operator_already_set_are_left_alone(
        self, world: _World
    ) -> None:
        # Sundays only, deliberately. Adding Mon-Sat "helpfully" would open a
        # business that has said it is shut.
        existing = Location(tenant_id=TENANT, name="Marina Branch")
        world.locations.append(existing)
        world.rules.append(
            AvailabilityRule(
                tenant_id=TENANT,
                owner_kind="location",
                owner_id=existing.id,
                weekday=6,
                start_time=time(10, 0),
                end_time=time(13, 0),
            )
        )

        await _seed(world)

        assert [r.weekday for r in world.rules] == [6]

    async def test_a_service_restricted_to_one_practitioner_gains_nobody(
        self, world: _World
    ) -> None:
        location = Location(tenant_id=TENANT, name="Marina Branch")
        service = Service(tenant_id=TENANT, name="Root canal", duration_minutes=60)
        specialist = Resource(tenant_id=TENANT, name="Dr Khan")
        world.locations.append(location)
        world.services.append(service)
        world.resources.append(specialist)
        world.eligibility.append(
            ServiceResource(
                tenant_id=TENANT, service_id=service.id, resource_id=specialist.id
            )
        )

        await _seed(world)

        assert len(world.eligibility) == 1
        assert len(world.services) == 1
        assert len(world.resources) == 1

    async def test_only_the_missing_piece_is_filled_in(self, world: _World) -> None:
        # The common half-finished case: a location and a service exist, nobody
        # has added staff. That one row is what is created.
        world.locations.append(Location(tenant_id=TENANT, name="Marina Branch"))
        world.services.append(
            Service(tenant_id=TENANT, name="Cleaning", duration_minutes=30)
        )

        report = await _seed(world)

        assert len(world.resources) == 1
        assert [s.name for s in world.services] == ["Cleaning"]
        assert not any("Service" in line for line in report.created)
