"""The appointment tools an AI agent is given (spec section 61).

The property under test is the one that matters: an agent cannot produce an
appointment time. Every slot it can offer came from the availability engine, and
holding one goes through the same path a human booking does — so a model that
hallucinates "3pm works" fails at the engine rather than at a prompt instruction.

Hermetic: the unit of work is faked in memory, so these run in CI with no
database and actually fail when the guarantee regresses.
"""

from __future__ import annotations

from datetime import UTC, datetime, time, timedelta
from zoneinfo import ZoneInfo

import pytest
from src.application.agent.tools import ToolContext
from src.domain.scheduling.availability import Interval
from src.domain.scheduling.entities import (
    AvailabilityRule,
    Location,
    Resource,
    Service,
    ServiceResource,
)
from src.domain.shared.errors import ConflictError
from src.domain.shared.identifiers import ResourceId, TenantId, new_id
from src.infrastructure.agent.scheduling_tools import (
    CreateSlotHoldTool,
    FindAvailableSlotsTool,
    ListServicesTool,
    build_scheduling_tools,
)

TENANT = TenantId(new_id())
OTHER_TENANT = TenantId(new_id())


def _next_monday() -> datetime:
    """The next Monday at least a week out, at 00:00 UTC.

    Relative to the real clock rather than a fixed date, because these tools
    deliberately read `datetime.now()` — that is the production path, and a
    hard-coded date would make the suite start failing the moment it went past.
    A week's margin keeps the slots clear of any minimum-notice rule.
    """
    base = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    base += timedelta(days=7)
    return base + timedelta(days=(7 - base.weekday()) % 7 or 7)


MONDAY = _next_monday()
# 09:00 at a UTC+4 branch is 05:00 UTC — the first slot of the day.
FIRST_SLOT = MONDAY + timedelta(hours=5)
# 07:00 local, before the branch opens: a time the engine will never offer.
BEFORE_OPENING = MONDAY + timedelta(hours=3)
# The same Monday as the branch in Dubai sees it. The tool reads `date` in the
# branch's zone, so the test must speak the same language.
MONDAY_LOCAL_DATE = (MONDAY + timedelta(hours=5)).astimezone(
    ZoneInfo("Asia/Dubai")
).date().isoformat()


class _FakeUow:
    """An in-memory stand-in for the scheduling half of the unit of work.

    Only the methods the tools reach for. Written as a fake rather than a mock so
    a tenant filter that is silently dropped shows up as a test failure instead
    of an assertion nobody wrote.
    """

    def __init__(self, world: _World) -> None:
        self._w = world
        self.locations = _FakeLocations(world)
        self.services = _FakeServices(world)
        self.resources = _FakeResources(world)
        self.availability = _FakeAvailability(world)
        self.reservations = _FakeReservations(world)
        self.scoped_to: TenantId | None = None

    async def __aenter__(self) -> _FakeUow:
        return self

    async def __aexit__(self, *args: object) -> None:
        return None

    def set_tenant_scope(self, tenant_id) -> None:  # type: ignore[no-untyped-def]
        self.scoped_to = tenant_id

    async def commit(self) -> None:
        self._w.commits += 1

    async def flush(self) -> None:
        return None

    def collect_event(self, event: object) -> None:
        self._w.events.append(event)


class _FakeLocations:
    def __init__(self, w: _World) -> None:
        self._w = w

    async def get(self, tenant_id, location_id):  # type: ignore[no-untyped-def]
        loc = self._w.locations.get(location_id)
        return loc if loc and loc.tenant_id == tenant_id else None

    async def list_for_tenant(self, tenant_id, *, active_only=False):  # type: ignore[no-untyped-def]
        return [
            loc
            for loc in self._w.locations.values()
            if loc.tenant_id == tenant_id and (not active_only or loc.is_active)
        ]


class _FakeServices:
    def __init__(self, w: _World) -> None:
        self._w = w

    async def get(self, tenant_id, service_id):  # type: ignore[no-untyped-def]
        svc = self._w.services.get(service_id)
        return svc if svc and svc.tenant_id == tenant_id else None

    async def list_for_tenant(self, tenant_id, *, active_only=False):  # type: ignore[no-untyped-def]
        return [
            s
            for s in self._w.services.values()
            if s.tenant_id == tenant_id and (not active_only or s.is_active)
        ]

    async def eligibility_for(self, tenant_id, service_id):  # type: ignore[no-untyped-def]
        return [
            link
            for link in self._w.eligibility
            if link.tenant_id == tenant_id and link.service_id == service_id
        ]


class _FakeResources:
    def __init__(self, w: _World) -> None:
        self._w = w

    async def list_by_ids(self, tenant_id, ids):  # type: ignore[no-untyped-def]
        return [
            r
            for r in self._w.resources.values()
            if r.tenant_id == tenant_id and r.id in set(ids)
        ]


class _FakeAvailability:
    def __init__(self, w: _World) -> None:
        self._w = w

    async def rules_for_owners(self, tenant_id, owner_ids):  # type: ignore[no-untyped-def]
        grouped: dict[object, list[AvailabilityRule]] = {}
        for rule in self._w.rules:
            if rule.tenant_id == tenant_id and rule.owner_id in set(owner_ids):
                grouped.setdefault(rule.owner_id, []).append(rule)
        return grouped

    async def blocks_for_owners(self, tenant_id, owner_ids, start, end):  # type: ignore[no-untyped-def]
        return {}


class _FakeReservations:
    def __init__(self, w: _World) -> None:
        self._w = w

    async def busy_intervals(self, tenant_id, resource_ids, start, end, now):  # type: ignore[no-untyped-def]
        return {
            rid: intervals
            for rid, intervals in self._w.busy.items()
            if rid in set(resource_ids)
        }

    async def purge_expired_holds(self, tenant_id, resource_ids, now):  # type: ignore[no-untyped-def]
        self._w.purged += 1
        return 0

    async def reserve(self, tenant_id, resource_ids, window, **kwargs):  # type: ignore[no-untyped-def]
        # Stands in for the database's exclusion constraint. The real guarantee
        # is Postgres's; this only lets the tool's failure path be tested.
        if self._w.reserve_conflicts:
            raise ConflictError("That time was just taken. Please choose another slot.")
        self._w.reserved.append((tuple(resource_ids), window, kwargs))


class _World:
    """The fabricated tenant these tests run against."""

    def __init__(self) -> None:
        self.locations: dict = {}
        self.services: dict = {}
        self.resources: dict = {}
        self.eligibility: list[ServiceResource] = []
        self.rules: list[AvailabilityRule] = []
        self.busy: dict[ResourceId, list[Interval]] = {}
        self.reserved: list = []
        self.events: list = []
        self.commits = 0
        self.purged = 0
        self.reserve_conflicts = False

    def uow_factory(self):  # type: ignore[no-untyped-def]
        return _FakeUow(self)


@pytest.fixture
def world() -> _World:
    w = _World()
    location = Location(
        tenant_id=TENANT, name="Dubai Clinic", timezone="Asia/Dubai"
    )
    service = Service(
        tenant_id=TENANT, name="Physiotherapy", duration_minutes=45
    )
    doctor = Resource(tenant_id=TENANT, name="Dr Khan")

    w.locations[location.id] = location
    w.services[service.id] = service
    w.resources[doctor.id] = doctor
    w.eligibility.append(
        ServiceResource(
            tenant_id=TENANT, service_id=service.id, resource_id=doctor.id
        )
    )
    # Open every weekday, 09:00-17:00 local.
    for weekday in range(5):
        w.rules.append(
            AvailabilityRule(
                tenant_id=TENANT,
                owner_kind="location",
                owner_id=location.id,
                weekday=weekday,
                start_time=time(9, 0),
                end_time=time(17, 0),
            )
        )
    w.location = location  # type: ignore[attr-defined]
    w.service = service  # type: ignore[attr-defined]
    w.doctor = doctor  # type: ignore[attr-defined]
    return w


def _ctx(tenant: TenantId = TENANT) -> ToolContext:
    return ToolContext(tenant_id=tenant)


class TestListServices:
    async def test_it_returns_real_ids_the_agent_can_use(self, world: _World) -> None:
        result = await ListServicesTool(world.uow_factory).run(_ctx())
        assert result.ok
        assert "Physiotherapy" in result.observation
        assert str(world.service.id) in result.observation  # type: ignore[attr-defined]
        assert str(world.location.id) in result.observation  # type: ignore[attr-defined]

    async def test_a_tenant_with_nothing_configured_is_told_so_plainly(self) -> None:
        # The agent must not improvise a service catalogue.
        empty = _World()
        result = await ListServicesTool(empty.uow_factory).run(_ctx())
        assert "no bookable services" in result.observation
        assert result.data["services"] == []

    async def test_a_service_that_is_not_online_bookable_is_withheld(
        self, world: _World
    ) -> None:
        world.service.online_bookable = False  # type: ignore[attr-defined]
        result = await ListServicesTool(world.uow_factory).run(_ctx())
        assert "no bookable services" in result.observation

    async def test_another_tenants_catalogue_is_invisible(self, world: _World) -> None:
        result = await ListServicesTool(world.uow_factory).run(_ctx(OTHER_TENANT))
        assert result.data["services"] == []
        assert result.data["locations"] == []


class TestFindAvailableSlots:
    async def test_it_returns_only_engine_computed_times(self, world: _World) -> None:
        tool = FindAvailableSlotsTool(world.uow_factory)
        result = await tool.run(
            _ctx(),
            service_id=str(world.service.id),  # type: ignore[attr-defined]
            location_id=str(world.location.id),  # type: ignore[attr-defined]
            date=MONDAY_LOCAL_DATE,
        )
        assert result.ok
        assert result.data["slots"], "an open Monday must yield slots"
        # 09:00 Dubai is 05:00 UTC. The agent is shown local time and handed the
        # UTC instant to pass back.
        first = result.data["slots"][0]
        assert first["starts_at"] == FIRST_SLOT.isoformat()
        assert "09:00" in result.observation

    async def test_it_tells_the_agent_not_to_invent_a_time_when_there_are_none(
        self, world: _World
    ) -> None:
        world.rules.clear()  # closed
        tool = FindAvailableSlotsTool(world.uow_factory)
        result = await tool.run(
            _ctx(),
            service_id=str(world.service.id),  # type: ignore[attr-defined]
            location_id=str(world.location.id),  # type: ignore[attr-defined]
            date=MONDAY_LOCAL_DATE,
        )
        assert result.data["slots"] == []
        assert "do not invent a time" in result.observation

    async def test_the_observation_instructs_the_agent_to_offer_only_these(
        self, world: _World
    ) -> None:
        tool = FindAvailableSlotsTool(world.uow_factory)
        result = await tool.run(
            _ctx(),
            service_id=str(world.service.id),  # type: ignore[attr-defined]
            location_id=str(world.location.id),  # type: ignore[attr-defined]
            date=MONDAY_LOCAL_DATE,
        )
        assert "Offer ONLY these times" in result.observation

    async def test_existing_bookings_are_excluded(self, world: _World) -> None:
        world.busy[world.doctor.id] = [  # type: ignore[attr-defined]
            Interval(FIRST_SLOT, FIRST_SLOT + timedelta(hours=3))
        ]
        tool = FindAvailableSlotsTool(world.uow_factory)
        result = await tool.run(
            _ctx(),
            service_id=str(world.service.id),  # type: ignore[attr-defined]
            location_id=str(world.location.id),  # type: ignore[attr-defined]
            date=MONDAY_LOCAL_DATE,
        )
        starts = {s["starts_at"] for s in result.data["slots"]}
        assert FIRST_SLOT.isoformat() not in starts
        assert starts, "the rest of the day is still bookable"

    async def test_a_missing_id_is_a_recoverable_tool_error(self, world: _World) -> None:
        # `ok=False` becomes an observation the planner can act on, rather than
        # an exception that ends the run.
        result = await FindAvailableSlotsTool(world.uow_factory).run(_ctx())
        assert not result.ok
        assert "list_services first" in result.observation

    async def test_a_garbage_id_does_not_raise(self, world: _World) -> None:
        result = await FindAvailableSlotsTool(world.uow_factory).run(
            _ctx(), service_id="not-a-uuid", location_id="also-not"
        )
        assert not result.ok

    async def test_another_tenants_service_is_not_found(self, world: _World) -> None:
        result = await FindAvailableSlotsTool(world.uow_factory).run(
            _ctx(OTHER_TENANT),
            service_id=str(world.service.id),  # type: ignore[attr-defined]
            location_id=str(world.location.id),  # type: ignore[attr-defined]
            date=MONDAY_LOCAL_DATE,
        )
        # Reads as absent rather than forbidden, so an id probe learns nothing.
        assert not result.ok
        assert "not found" in result.observation.lower()

    async def test_the_observation_is_bounded(self, world: _World) -> None:
        # A whole week at 15-minute granularity is hundreds of slots; an agent
        # reading them aloud needs a handful.
        result = await FindAvailableSlotsTool(world.uow_factory).run(
            _ctx(),
            service_id=str(world.service.id),  # type: ignore[attr-defined]
            location_id=str(world.location.id),  # type: ignore[attr-defined]
            date=MONDAY_LOCAL_DATE,
        )
        assert len(result.data["slots"]) <= 8


class TestCreateSlotHold:
    async def test_holding_an_offered_slot_succeeds_and_returns_a_token(
        self, world: _World
    ) -> None:
        result = await CreateSlotHoldTool(world.uow_factory).run(
            _ctx(),
            service_id=str(world.service.id),  # type: ignore[attr-defined]
            location_id=str(world.location.id),  # type: ignore[attr-defined]
            starts_at=FIRST_SLOT.isoformat(),
        )
        assert result.ok, result.observation
        assert result.data["hold_token"]
        assert world.reserved, "a hold must actually claim the resource"

    async def test_a_time_the_engine_never_offered_is_refused(
        self, world: _World
    ) -> None:
        # The heart of section 61: a hallucinated 3am fails at the engine.
        result = await CreateSlotHoldTool(world.uow_factory).run(
            _ctx(),
            service_id=str(world.service.id),  # type: ignore[attr-defined]
            location_id=str(world.location.id),  # type: ignore[attr-defined]
            starts_at=BEFORE_OPENING.isoformat(),  # 07:00 Dubai, before opening
        )
        assert not result.ok
        assert not world.reserved

    async def test_losing_the_race_tells_the_agent_what_to_do_next(
        self, world: _World
    ) -> None:
        world.reserve_conflicts = True
        result = await CreateSlotHoldTool(world.uow_factory).run(
            _ctx(),
            service_id=str(world.service.id),  # type: ignore[attr-defined]
            location_id=str(world.location.id),  # type: ignore[attr-defined]
            starts_at=FIRST_SLOT.isoformat(),
        )
        assert not result.ok
        # An agent told only "failed" will improvise. Told what to do, it recovers.
        assert "find_available_slots again" in result.observation

    async def test_a_failed_hold_never_claims_anything(self, world: _World) -> None:
        world.reserve_conflicts = True
        await CreateSlotHoldTool(world.uow_factory).run(
            _ctx(),
            service_id=str(world.service.id),  # type: ignore[attr-defined]
            location_id=str(world.location.id),  # type: ignore[attr-defined]
            starts_at=FIRST_SLOT.isoformat(),
        )
        assert world.reserved == []

    async def test_missing_arguments_are_a_recoverable_error(
        self, world: _World
    ) -> None:
        result = await CreateSlotHoldTool(world.uow_factory).run(_ctx())
        assert not result.ok
        assert "find_available_slots" in result.observation


class TestRegistration:
    def test_the_tools_have_distinct_names_and_usable_specs(self) -> None:
        tools = build_scheduling_tools(_World().uow_factory)
        names = [t.spec.name for t in tools]
        # Read-only tools first, then the ones that change something: this is the
        # order they appear in the planner's catalogue, which a model reads as a
        # rough sequence.
        assert names == [
            "list_services",
            "find_available_slots",
            "find_customer_appointments",
            "create_slot_hold",
            "book_appointment",
            "reschedule_appointment",
            "cancel_appointment",
        ]
        assert len(set(names)) == len(names)

    def test_every_description_forbids_inventing_a_slot(self) -> None:
        # The prompt-level half of section 61. The structural half is that the
        # tools simply cannot return a time the engine did not produce.
        tools = build_scheduling_tools(_World().uow_factory)
        find = next(t for t in tools if t.spec.name == "find_available_slots")
        hold = next(t for t in tools if t.spec.name == "create_slot_hold")
        assert "never guess or invent" in find.spec.description
        assert "Never tell a customer a slot is held unless this succeeds" in (
            hold.spec.description
        )

    def test_the_tools_are_registrable_in_the_agent_registry(self) -> None:
        from src.application.agent.registry import ToolRegistry

        registry = ToolRegistry(build_scheduling_tools(_World().uow_factory))
        assert registry.get("find_available_slots") is not None
        # The catalogue is what the planner actually reads.
        assert "find_available_slots" in registry.render_catalog()
