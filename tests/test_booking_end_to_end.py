"""A whole booking, start to finish, through the parts that run in production.

The unit tests each pin one link: the gate, the spread, the seeding, the
engine. This is the one that answers the question an operator actually asks —
"I turned it on, will it book?" — by running the real agent loop over the real
registry, the real tools and the real `BookAppointment` use case, with only the
database and the model replaced.

The model is scripted rather than live for the usual reason: an LLM makes this
test flaky without making it stronger. Every JSON action below is one a real
model emitted while this feature was being driven by hand, so the transcript is
the shape production traffic actually has — including the part that matters
most, which is that the agent never types a time of its own.

What is genuinely under test:

  * enabling booking on a bare workspace leaves it able to book at all,
  * the assistant given permission gets a real appointment row, with the
    customer's details on it, in the state the Appointments page reads,
  * an assistant *without* permission gets nowhere near one.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from src.application.agent.loop import AgentLoop
from src.application.agent.registry import ToolRegistry
from src.application.agent.router import ModelRouter
from src.application.agent.tools import ToolContext
from src.application.ports.repositories import HeldReservation
from src.application.ports.services import LLMResult
from src.application.use_cases.booking_setup import EnsureBookingSetup
from src.domain.chatbot.entities import AssistantConfig, Chatbot
from src.domain.scheduling.availability import Interval
from src.domain.scheduling.entities import (
    Appointment,
    AvailabilityRule,
    Location,
    Resource,
    Service,
    ServiceResource,
    StatusChange,
)
from src.domain.shared.errors import ConflictError
from src.domain.shared.identifiers import TenantId, new_id
from src.domain.tenant.entities import Tenant
from src.infrastructure.agent.front_office import (
    FRONT_OFFICE_REFUSAL,
    FRONT_OFFICE_SYSTEM,
)
from src.infrastructure.agent.scheduling_tools import build_scheduling_tools

TENANT = TenantId(new_id())


# --------------------------------------------------------------------------
# The workspace, in memory. Everything the booking path touches, and nothing
# else — written as a fake so a dropped tenant filter fails a test.
# --------------------------------------------------------------------------


@dataclass
class _Reservation:
    resource_id: Any
    window: Interval
    kind: str
    appointment_id: Any = None
    hold_token: str | None = None
    expires_at: datetime | None = None
    released: bool = False


class _World:
    def __init__(self) -> None:
        self.tenant = Tenant(name="Bright Smile Dental", slug="bright-smile", id=TENANT)
        self.chatbots: dict[Any, Chatbot] = {}
        self.locations: list[Location] = []
        self.services: list[Service] = []
        self.resources: list[Resource] = []
        self.eligibility: list[ServiceResource] = []
        self.rules: list[AvailabilityRule] = []
        self.reservations: list[_Reservation] = []
        self.appointments: list[Appointment] = []
        self.history: list[StatusChange] = []
        self.events: list[Any] = []

    def uow_factory(self) -> _FakeUow:
        return _FakeUow(self)

    def add_assistant(self, *, books: bool, name: str) -> Chatbot:
        bot = Chatbot(
            tenant_id=TENANT,
            name=name,
            assistant=AssistantConfig(appointments_enabled=books),
        )
        self.chatbots[bot.id] = bot
        return bot

    def live_reservations(self) -> list[_Reservation]:
        return [r for r in self.reservations if not r.released]


class _FakeUow:
    def __init__(self, w: _World) -> None:
        self._w = w
        self.tenants = _FakeTenants(w)
        self.chatbots = _FakeChatbots(w)
        self.locations = _FakeLocations(w)
        self.services = _FakeServices(w)
        self.resources = _FakeResources(w)
        self.availability = _FakeAvailability(w)
        self.reservations = _FakeReservations(w)
        self.appointments = _FakeAppointments(w)
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
        return None

    def collect_event(self, event: object) -> None:
        self._w.events.append(event)


class _FakeTenants:
    def __init__(self, w: _World) -> None:
        self._w = w

    async def get(self, tenant_id):  # type: ignore[no-untyped-def]
        return self._w.tenant if tenant_id == self._w.tenant.id else None


class _FakeChatbots:
    def __init__(self, w: _World) -> None:
        self._w = w

    async def get(self, tenant_id, chatbot_id):  # type: ignore[no-untyped-def]
        bot = self._w.chatbots.get(chatbot_id)
        return bot if bot and bot.tenant_id == tenant_id else None


class _FakeLocations:
    def __init__(self, w: _World) -> None:
        self._w = w

    async def add(self, location: Location) -> None:
        self._w.locations.append(location)

    async def get(self, tenant_id, location_id):  # type: ignore[no-untyped-def]
        return next(
            (
                loc
                for loc in self._w.locations
                if loc.id == location_id and loc.tenant_id == tenant_id
            ),
            None,
        )

    async def list_for_tenant(self, tenant_id, *, active_only=False):  # type: ignore[no-untyped-def]
        return [loc for loc in self._w.locations if loc.tenant_id == tenant_id]


class _FakeServices:
    def __init__(self, w: _World) -> None:
        self._w = w

    async def add(self, service: Service) -> None:
        self._w.services.append(service)

    async def get(self, tenant_id, service_id):  # type: ignore[no-untyped-def]
        return next(
            (
                s
                for s in self._w.services
                if s.id == service_id and s.tenant_id == tenant_id
            ),
            None,
        )

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

    async def list_by_ids(self, tenant_id, ids):  # type: ignore[no-untyped-def]
        wanted = set(ids)
        return [
            r for r in self._w.resources if r.tenant_id == tenant_id and r.id in wanted
        ]


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

    async def rules_for_owners(self, tenant_id, owner_ids):  # type: ignore[no-untyped-def]
        wanted = set(owner_ids)
        grouped: dict[object, list[AvailabilityRule]] = {}
        for rule in self._w.rules:
            if rule.tenant_id == tenant_id and rule.owner_id in wanted:
                grouped.setdefault(rule.owner_id, []).append(rule)
        return grouped

    async def blocks_for_owners(self, tenant_id, owner_ids, start, end):  # type: ignore[no-untyped-def]
        return {}


class _FakeReservations:
    """Stands in for the exclusion constraint, honestly enough to matter.

    An overlapping claim on the same resource raises `ConflictError`, which is
    what the real GiST constraint does — so a hold genuinely makes the slot
    unbookable inside this test, rather than merely being recorded.
    """

    def __init__(self, w: _World) -> None:
        self._w = w

    async def busy_intervals(self, tenant_id, resource_ids, start, end, now):  # type: ignore[no-untyped-def]
        wanted = set(resource_ids)
        busy: dict[Any, list[Interval]] = {}
        for r in self._w.live_reservations():
            if r.resource_id in wanted and r.window.overlaps(Interval(start, end)):
                busy.setdefault(r.resource_id, []).append(r.window)
        return busy

    async def purge_expired_holds(self, tenant_id, resource_ids, now):  # type: ignore[no-untyped-def]
        expired = [
            r
            for r in self._w.live_reservations()
            if r.kind == "hold" and r.expires_at and r.expires_at <= now
        ]
        for r in expired:
            r.released = True
        return len(expired)

    async def reserve(
        self, tenant_id, resource_ids, window, *, kind, appointment_id=None,
        hold_token=None, expires_at=None,
    ):  # type: ignore[no-untyped-def]
        for resource_id in resource_ids:
            clash = any(
                r.resource_id == resource_id and r.window.overlaps(window)
                for r in self._w.live_reservations()
            )
            if clash:
                raise ConflictError("That time was just taken. Please choose another slot.")
        for resource_id in resource_ids:
            self._w.reservations.append(
                _Reservation(
                    resource_id=resource_id,
                    window=window,
                    kind=kind,
                    appointment_id=appointment_id,
                    hold_token=hold_token,
                    expires_at=expires_at,
                )
            )

    async def hold_by_token(self, tenant_id, token, now):  # type: ignore[no-untyped-def]
        return [
            HeldReservation(
                resource_id=r.resource_id,
                starts_at=r.window.start,
                ends_at=r.window.end,
            )
            for r in self._w.live_reservations()
            if r.hold_token == token and (r.expires_at is None or r.expires_at > now)
        ]

    async def convert_hold(self, tenant_id, token, appointment_id):  # type: ignore[no-untyped-def]
        converted = 0
        for r in self._w.live_reservations():
            if r.hold_token == token:
                r.kind = "booking"
                r.appointment_id = appointment_id
                r.hold_token = None
                r.expires_at = None
                converted += 1
        return converted

    async def release_for_appointment(self, tenant_id, appointment_id, now):  # type: ignore[no-untyped-def]
        released = [
            r for r in self._w.live_reservations() if r.appointment_id == appointment_id
        ]
        for r in released:
            r.released = True
        return len(released)


class _FakeAppointments:
    def __init__(self, w: _World) -> None:
        self._w = w

    async def add(self, appointment: Appointment) -> None:
        self._w.appointments.append(appointment)

    async def get_by_idempotency_key(self, tenant_id, key):  # type: ignore[no-untyped-def]
        return next(
            (
                a
                for a in self._w.appointments
                if a.tenant_id == tenant_id and a.idempotency_key == key and key
            ),
            None,
        )

    async def add_status_change(self, change: StatusChange) -> None:
        self._w.history.append(change)

    async def list_for_tenant(self, tenant_id, **kwargs):  # type: ignore[no-untyped-def]
        statuses = kwargs.get("statuses")
        window_start = kwargs.get("window_start")
        return [
            a
            for a in self._w.appointments
            if a.tenant_id == tenant_id
            and (statuses is None or a.status in statuses)
            and (window_start is None or a.ends_at >= window_start)
        ]


# --------------------------------------------------------------------------
# The model, scripted.
# --------------------------------------------------------------------------


class _ScriptedLLM:
    """Replays a planner transcript, and records what it was asked.

    Each entry is either a JSON action (what a planner emits) or a callable that
    builds one from the running transcript — needed for the steps whose input is
    an id or a `starts_at` the tools only just produced, which is precisely the
    part that must come from the backend rather than from the model.
    """

    name = "scripted"

    def __init__(self, script: list[Any]) -> None:
        self._script = list(script)
        self.prompts: list[str] = []

    async def generate(self, system: str, user: str) -> LLMResult:
        self.prompts.append(user)
        if not self._script:
            raise AssertionError(
                "the agent took more steps than the script had answers for; "
                f"last transcript:\n{user[-2000:]}"
            )
        nxt = self._script.pop(0)
        text = nxt(user) if callable(nxt) else nxt
        return LLMResult(text=text, tokens_used=12, provider="scripted", model="scripted-1")


def _action(name: str, **inputs: Any) -> str:
    return json.dumps({"thought": "…", "action": name, "action_input": inputs})


def _last(transcript: str, marker: str, end: str) -> str:
    """Pull a value the tools put in the observation — an id, a starts_at.

    Reading it out of the transcript rather than out of the fixture is the point:
    it proves the value the agent books with is one the backend handed it.
    """
    start = transcript.rindex(marker) + len(marker)
    return transcript[start : transcript.index(end, start)]


def _agent(world: _World, script: list[Any]) -> tuple[AgentLoop, _ScriptedLLM]:
    llm = _ScriptedLLM(script)
    return (
        AgentLoop(
            ToolRegistry(build_scheduling_tools(world.uow_factory)),
            ModelRouter(cheap=llm),
            refusal_answer=FRONT_OFFICE_REFUSAL,
            max_steps=10,
            system_template=FRONT_OFFICE_SYSTEM,
        ),
        llm,
    )


def _next_open_day(world: _World) -> str:
    """A local date the seeded hours are actually open on, a week out."""
    zone = ZoneInfo(world.locations[0].timezone)
    day = (datetime.now(UTC) + timedelta(days=7)).astimezone(zone).date()
    while day.weekday() not in {r.weekday for r in world.rules}:
        day += timedelta(days=1)
    return day.isoformat()


async def _a_free_slot(world: _World) -> datetime:
    """A start time the engine really would accept, asked of the engine itself."""
    from src.application.use_cases.availability import FindAvailability
    from src.domain.shared.identifiers import LocationId, ServiceId

    zone = ZoneInfo(world.locations[0].timezone)
    day = datetime.fromisoformat(_next_open_day(world)).date()
    start = datetime.combine(day, datetime.min.time(), tzinfo=zone).astimezone(UTC)
    slots, _, _ = await FindAvailability(world.uow_factory()).execute(
        TENANT,
        location_id=LocationId(world.locations[0].id),
        service_id=ServiceId(world.services[0].id),
        range_start=start,
        range_end=start + timedelta(days=1),
        limit=10,
    )
    assert slots, "the seeded workspace produced no bookable time at all"
    return slots[0].starts_at


@pytest.fixture
async def world() -> _World:
    """A workspace that has just had booking switched on and nothing else.

    Deliberately bare: this is the state the operator reported as broken, and
    the seed is part of what is being tested rather than test scaffolding.
    """
    w = _World()
    await EnsureBookingSetup(w.uow_factory()).execute(TENANT, timezone="Asia/Dubai")
    return w


class TestAnEnabledAssistantBooksSomethingReal:
    async def test_a_bare_workspace_can_book_after_the_switch_is_turned_on(
        self, world: _World
    ) -> None:
        booker = world.add_assistant(books=True, name="Reception")
        day = _next_open_day(world)

        loop, llm = _agent(
            world,
            [
                _action("list_services"),
                lambda t: _action(
                    "find_available_slots",
                    service_id=_last(t, "[service_id=", "]"),
                    location_id=_last(t, "(location_id=", ","),
                    date=day,
                ),
                lambda t: _action(
                    "create_slot_hold",
                    service_id=_last(t, "[service_id=", "]"),
                    location_id=_last(t, "(location_id=", ","),
                    starts_at=_last(t, "1. ", ")").split("starts_at=")[1],
                ),
                lambda t: _action(
                    "book_appointment",
                    service_id=_last(t, "[service_id=", "]"),
                    location_id=_last(t, "(location_id=", ","),
                    starts_at=_last(t, "Held ", " until"),
                    customer_name="Aisha Rahman",
                    customer_phone="+971500000001",
                    reason_for_visit="Toothache on the left side",
                    hold_token=_last(t, "Hold token: ", "."),
                ),
                lambda t: _action(
                    "final",
                    answer=f"You're booked — reference {_last(t, 'Reference ', '.')}",
                ),
            ],
        )

        result = await loop.run(
            ToolContext(
                tenant_id=TENANT,
                chatbot_id=booker.id,
                extras={"source": "web_widget", "channel": "web", "conversation_id": "c1"},
            ),
            "I've got a toothache, can I come in?",
        )

        # The row itself — the thing the Appointments page lists.
        assert len(world.appointments) == 1, "no appointment was created"
        appointment = world.appointments[0]
        assert appointment.customer_name == "Aisha Rahman"
        assert appointment.customer_phone == "+971500000001"
        assert appointment.customer_notes == "Toothache on the left side"
        assert appointment.status == "confirmed"
        assert appointment.source == "web_widget"
        assert appointment.starts_at > datetime.now(UTC)
        # And the answer quotes the backend's reference rather than inventing one.
        assert appointment.id.hex[:8].upper() in result.answer
        assert result.trace.stop_reason == "final"

    async def test_the_booked_time_is_one_the_engine_offered(
        self, world: _World
    ) -> None:
        # Section 61, end to end: the instant on the row came out of
        # find_available_slots, through a hold, and was never typed by the model.
        booker = world.add_assistant(books=True, name="Reception")
        day = _next_open_day(world)
        offered: list[str] = []

        def remember_and_hold(t: str) -> str:
            offered.extend(
                line.split("starts_at=")[1].rstrip(")")
                for line in t.splitlines()
                if "starts_at=" in line
            )
            return _action(
                "create_slot_hold",
                service_id=_last(t, "[service_id=", "]"),
                location_id=_last(t, "(location_id=", ","),
                starts_at=offered[0],
            )

        loop, _ = _agent(
            world,
            [
                _action("list_services"),
                lambda t: _action(
                    "find_available_slots",
                    service_id=_last(t, "[service_id=", "]"),
                    location_id=_last(t, "(location_id=", ","),
                    date=day,
                ),
                remember_and_hold,
                lambda t: _action(
                    "book_appointment",
                    service_id=_last(t, "[service_id=", "]"),
                    location_id=_last(t, "(location_id=", ","),
                    starts_at=_last(t, "Held ", " until"),
                    customer_name="Aisha Rahman",
                    customer_email="aisha@example.com",
                    hold_token=_last(t, "Hold token: ", "."),
                ),
                _action("final", answer="Done."),
            ],
        )

        await loop.run(
            ToolContext(tenant_id=TENANT, chatbot_id=booker.id, extras={"conversation_id": "c2"}),
            "Anything on that day?",
        )

        assert world.appointments[0].starts_at.isoformat() in offered

    async def test_the_slot_is_claimed_so_nobody_else_can_take_it(
        self, world: _World
    ) -> None:
        # The hold is converted, not left beside the booking — a second claim on
        # the same resource and window raises, exactly as the database would.
        booker = world.add_assistant(books=True, name="Reception")
        day = _next_open_day(world)
        loop, _ = _agent(
            world,
            [
                _action("list_services"),
                lambda t: _action(
                    "find_available_slots",
                    service_id=_last(t, "[service_id=", "]"),
                    location_id=_last(t, "(location_id=", ","),
                    date=day,
                ),
                lambda t: _action(
                    "create_slot_hold",
                    service_id=_last(t, "[service_id=", "]"),
                    location_id=_last(t, "(location_id=", ","),
                    starts_at=_last(t, "1. ", ")").split("starts_at=")[1],
                ),
                lambda t: _action(
                    "book_appointment",
                    service_id=_last(t, "[service_id=", "]"),
                    location_id=_last(t, "(location_id=", ","),
                    starts_at=_last(t, "Held ", " until"),
                    customer_name="Aisha Rahman",
                    customer_phone="+971500000001",
                    hold_token=_last(t, "Hold token: ", "."),
                ),
                _action("final", answer="Done."),
            ],
        )
        await loop.run(
            ToolContext(tenant_id=TENANT, chatbot_id=booker.id, extras={"conversation_id": "c3"}),
            "Book me in.",
        )

        live = world.live_reservations()
        assert len(live) == 1
        assert live[0].kind == "booking"
        assert live[0].appointment_id == world.appointments[0].id
        assert live[0].hold_token is None, "the hold was left alive beside the booking"

    async def test_the_creation_is_recorded_in_the_appointment_history(
        self, world: _World
    ) -> None:
        # Attribution: the audit trail has to say the AI did this, or "who
        # booked this?" has no answer on the day someone asks.
        booker = world.add_assistant(books=True, name="Reception")
        day = _next_open_day(world)
        loop, _ = _agent(
            world,
            [
                _action("list_services"),
                lambda t: _action(
                    "find_available_slots",
                    service_id=_last(t, "[service_id=", "]"),
                    location_id=_last(t, "(location_id=", ","),
                    date=day,
                ),
                lambda t: _action(
                    "book_appointment",
                    service_id=_last(t, "[service_id=", "]"),
                    location_id=_last(t, "(location_id=", ","),
                    starts_at=_last(t, "1. ", ")").split("starts_at=")[1],
                    customer_name="Omar Said",
                    customer_phone="+971500000002",
                ),
                _action("final", answer="Done."),
            ],
        )
        await loop.run(
            ToolContext(tenant_id=TENANT, chatbot_id=booker.id, extras={"conversation_id": "c4"}),
            "Book me in.",
        )

        assert len(world.history) == 1
        assert world.history[0].actor_kind == "ai_agent"
        assert world.history[0].to_status == "confirmed"


class TestAnAssistantWithoutPermissionBooksNothing:
    async def test_it_cannot_even_see_the_service_catalogue(
        self, world: _World
    ) -> None:
        bystander = world.add_assistant(books=False, name="Support bot")
        loop, _ = _agent(
            world,
            [
                _action("list_services"),
                _action("final", answer="I can't take bookings here, sorry."),
            ],
        )

        result = await loop.run(
            ToolContext(tenant_id=TENANT, chatbot_id=bystander.id, extras={}),
            "Book me a cleaning tomorrow at 10.",
        )

        assert world.appointments == []
        assert "not allowed to handle appointments" in result.trace.steps[0].observation

    async def test_a_direct_attempt_to_book_is_refused(self, world: _World) -> None:
        # The realistic failure: a model that skips the read tools and goes
        # straight for the one that commits. Permission is checked there too.
        #
        # The time it tries is a genuinely bookable one, taken from the engine
        # beforehand — booking a time that was never free would be refused by
        # the engine anyway, and would pass this test with the gate deleted.
        bystander = world.add_assistant(books=False, name="Support bot")
        service = world.services[0]
        location = world.locations[0]
        bookable = await _a_free_slot(world)
        loop, _ = _agent(
            world,
            [
                _action(
                    "book_appointment",
                    service_id=str(service.id),
                    location_id=str(location.id),
                    starts_at=bookable.isoformat(),
                    customer_name="Aisha Rahman",
                    customer_phone="+971500000001",
                ),
                _action("final", answer="I can't take bookings here, sorry."),
            ],
        )

        await loop.run(
            ToolContext(tenant_id=TENANT, chatbot_id=bystander.id, extras={}),
            "Just book it.",
        )

        assert world.appointments == []
        assert world.live_reservations() == []

    async def test_the_permitted_assistant_is_unaffected_by_the_other_one(
        self, world: _World
    ) -> None:
        # Both assistants live in the same workspace and share the same tools.
        # Permission is per assistant, so one being refused must not be the
        # reason — or the effect — of anything happening to the other.
        world.add_assistant(books=False, name="Support bot")
        booker = world.add_assistant(books=True, name="Reception")
        day = _next_open_day(world)
        loop, _ = _agent(
            world,
            [
                _action("list_services"),
                lambda t: _action(
                    "find_available_slots",
                    service_id=_last(t, "[service_id=", "]"),
                    location_id=_last(t, "(location_id=", ","),
                    date=day,
                ),
                lambda t: _action(
                    "book_appointment",
                    service_id=_last(t, "[service_id=", "]"),
                    location_id=_last(t, "(location_id=", ","),
                    starts_at=_last(t, "1. ", ")").split("starts_at=")[1],
                    customer_name="Aisha Rahman",
                    customer_phone="+971500000001",
                ),
                _action("final", answer="Done."),
            ],
        )

        await loop.run(
            ToolContext(tenant_id=TENANT, chatbot_id=booker.id, extras={"conversation_id": "c5"}),
            "Book me in.",
        )

        assert len(world.appointments) == 1
