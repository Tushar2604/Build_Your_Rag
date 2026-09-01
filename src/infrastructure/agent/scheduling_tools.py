"""Appointment tools for the agent loop.

These exist so that spec section 61 — "the AI must never invent an available
slot" — is structurally true rather than a line in a prompt. The model has no
way to produce a time: `find_available_slots` returns slots the availability
engine computed, and `create_slot_hold` will only hold one of those. A
hallucinated 3pm fails at the engine, not at a guardrail.

Registered in `build_agent_loop`, so every channel that runs the loop (and, in
later phases, the WhatsApp and voice agents) gains booking with no changes to
the loop itself.

Phase 1 registers the read and reserve tools only. `book_appointment` arrives
with the channel that needs it, because booking on a customer's behalf needs the
identity and consent context a channel supplies — and a tool that can create a
real commitment should not be registered before anything is ready to use it.
"""

from __future__ import annotations

import hashlib
import uuid
from collections.abc import Callable
from datetime import UTC, date, datetime, time, timedelta
from typing import Any, cast
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import structlog

from src.application.agent.tools import ToolContext, ToolResult, ToolSpec
from src.application.ports.repositories import UnitOfWork
from src.application.use_cases.appointments import (
    BookAppointment,
    RescheduleAppointment,
    TransitionAppointment,
)
from src.application.use_cases.availability import FindAvailability, HoldSlot
from src.domain.scheduling.entities import ALL_SOURCES, MAX_NOTES, BookingSource
from src.domain.shared.errors import DomainError
from src.domain.shared.identifiers import (
    AppointmentId,
    LocationId,
    ResourceId,
    ServiceId,
)

log = structlog.get_logger(__name__)

UowFactory = Callable[[], UnitOfWork]

# How far ahead a tool will look when the model does not say. A week: long
# enough to answer "when can I come in?", short enough that the observation
# stays readable in a prompt.
DEFAULT_SEARCH_DAYS = 7
# How many slots the engine is asked for. Higher than what is shown, on purpose:
# the offer is picked from across the whole window (see `_spread_options`), and a
# short query would only ever return the first hour of the first open day.
SLOT_QUERY_LIMIT = 60
# What the customer is actually offered. Four is the most a person can hold in
# their head from a chat bubble, and the most a voice agent can read aloud
# without the caller losing the first one.
MAX_OFFERED_OPTIONS = 4
# Extra times kept in the observation so the agent can answer "anything later?"
# without a second tool call — but not so many that the transcript, which is
# re-sent on every reasoning step, doubles in size.
MAX_ALTERNATIVE_SLOTS = 8


def _friendly(moment: datetime) -> str:
    """A time a person would say out loud: "Mon 02 Sep, 9:00 AM".

    The agent is told to read options verbatim, so the readable form is built
    here rather than left to the model — a model asked to reformat an ISO string
    is a model given one more chance to change the time while it is at it.
    """
    hour = moment.strftime("%I").lstrip("0") or "12"
    return f"{moment:%a %d %b}, {hour}:{moment:%M} {moment:%p}"


def _spread_options(slots: list[Any], timezone: str) -> tuple[list[Any], list[Any]]:
    """Split the engine's slots into a few distinct offers, plus the rest.

    The engine returns every bookable start on a 15-minute grid, so the first
    four are 9:00, 9:15, 9:30, 9:45 — which is not a choice, it is the same
    appointment four times, and it reads to a customer as though the day is
    nearly full. Offering one slot per clock hour turns it back into the choice
    they were actually being given: 9, 10, 11, 12.

    Returns (offer, alternatives) — both real slots from the engine, so nothing
    here can put a time in front of a customer that is not genuinely bookable.
    """
    by_hour: dict[tuple[int, int, int, int], Any] = {}
    for slot in slots:
        local = _in_zone(slot.starts_at, timezone)
        key = (local.year, local.month, local.day, local.hour)
        # Earliest start in each hour: slots arrive in chronological order.
        by_hour.setdefault(key, slot)

    offer = list(by_hour.values())[:MAX_OFFERED_OPTIONS]
    # A day that genuinely only has 9:00 and 9:30 free should still offer both
    # rather than a single option — falling back to consecutive slots is right
    # exactly when there are no distinct hours left to spread across.
    # Keyed on the instant rather than on object identity: the engine yields one
    # slot per start time, so the start IS the identity here.
    if len(offer) < MAX_OFFERED_OPTIONS:
        offered = {s.starts_at for s in offer}
        for slot in slots:
            if len(offer) >= MAX_OFFERED_OPTIONS:
                break
            if slot.starts_at not in offered:
                offer.append(slot)
                offered.add(slot.starts_at)
        offer.sort(key=lambda s: s.starts_at)

    chosen = {s.starts_at for s in offer}
    alternatives = [s for s in slots if s.starts_at not in chosen][:MAX_ALTERNATIVE_SLOTS]
    return offer, alternatives


def _parse_dt(value: Any) -> datetime | None:
    """Accept what a model actually emits: ISO strings, with or without a zone.

    A naive value is read as UTC rather than rejected — the alternative is a tool
    error the planner has to recover from, for input that is unambiguous in
    practice because every instant in this system is UTC.
    """
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _parse_uuid(value: Any) -> uuid.UUID | None:
    if isinstance(value, uuid.UUID):
        return value
    if not isinstance(value, str):
        return None
    try:
        return uuid.UUID(value.strip())
    except ValueError:
        return None


# Statuses a customer would still call "my appointment". A cancelled one is not
# reschedulable and must not appear in a lookup.
LIVE_STATUSES = (
    "draft",
    "requested",
    "pending",
    "awaiting_confirmation",
    "confirmed",
    "arrived",
    "checked_in",
    "in_progress",
)


# Rough parts of the day, in branch-local hours. A customer says "evening", not
# "17:00-21:00", and turning the one into the other is arithmetic — so it is done
# here rather than asked of the model.
TIME_OF_DAY_HOURS: dict[str, tuple[int, int]] = {
    "morning": (6, 12),
    "afternoon": (12, 17),
    "evening": (17, 22),
    "any": (0, 24),
}


def _local_day_window(
    day: str, time_of_day: str, timezone: str, now: datetime
) -> tuple[datetime, datetime] | None:
    """Turn "2026-08-31" + "morning" into a UTC window, read in the branch's zone.

    This exists because the alternative is asking the model to do timezone
    arithmetic. It does not know the branch's offset, does not reliably know
    today's date, and gets both wrong in ways that look like "no availability"
    rather than like an error — which is how an AI receptionist tells a customer
    the clinic is closed on a day it is open.
    """
    try:
        zone = ZoneInfo(timezone or "UTC")
    except (ZoneInfoNotFoundError, ValueError):
        zone = ZoneInfo("UTC")

    try:
        target = date.fromisoformat(day.strip())
    except (ValueError, AttributeError):
        return None

    start_hour, end_hour = TIME_OF_DAY_HOURS.get(
        (time_of_day or "any").strip().lower(), TIME_OF_DAY_HOURS["any"]
    )
    start_local = datetime.combine(target, time(start_hour, 0), tzinfo=zone)
    end_local = (
        datetime.combine(target, time.max, tzinfo=zone)
        if end_hour >= 24
        else datetime.combine(target, time(end_hour, 0), tzinfo=zone)
    )
    # Never offer a time that has already passed today.
    return max(start_local.astimezone(UTC), now), end_local.astimezone(UTC)


def _reference(appointment_id: uuid.UUID) -> str:
    """A short handle a customer can read back over the phone.

    The first eight hex characters of the id, upper-cased. Not a new column: it
    is derived, so it cannot drift from the id, and `_resolve_reference` matches
    on the same prefix. Collisions inside one tenant's upcoming appointments are
    vanishingly unlikely, and the lookup is scoped to exactly that set.
    """
    return f"APT-{appointment_id.hex[:8].upper()}"


def _source_for(ctx: ToolContext) -> BookingSource:
    """Channel attribution (spec section 44), taken from what the channel said.

    Falls back to `api` rather than guessing: a wrong attribution silently
    corrupts the "which channel produces business" report, which is the whole
    point of storing it.
    """
    source = str(ctx.extras.get("source") or "").strip()
    # The membership check IS the validation, so the cast is safe — but it has
    # to be spelled out, because a value that reaches the appointment row
    # unchecked corrupts channel attribution silently.
    return cast("BookingSource", source) if source in ALL_SOURCES else "api"


# What a tool says when the assistant driving it was never given permission to
# book. Written as an instruction rather than an error, because the planner reads
# it as an observation and has to know what to do next — the failure mode being
# guarded against is an assistant that "helpfully" invents a booking when a tool
# refuses it.
BOOKING_NOT_PERMITTED = (
    "This assistant is not allowed to handle appointments. Do NOT offer a time, "
    "do NOT hold a slot, and do NOT tell the customer anything is booked, moved "
    "or cancelled. Say you can't take bookings here and offer to help with "
    "something else."
)


async def _assistant_may_book(uow_factory: UowFactory, ctx: ToolContext) -> bool:
    """Is the assistant behind this call the one the operator allowed to book?

    Permission lives on the assistant (`assistant.appointments_enabled`) and is
    checked here, at the tool, rather than only at the routing layer — because
    routing decides which agent *answers*, and there is more than one way for a
    loop to end up holding these tools (the shared document agent registers them
    whenever `APPOINTMENT_AGENT_TOOLS_ENABLED` is on, for every assistant in the
    deployment). Enforcing it once at the point of effect is what makes "only
    this assistant can book" true no matter which path got here.

    An anonymous context — no `chatbot_id`, so no assistant to have been given
    permission — is refused. Staff bookings do not come through the agent; they
    go through the appointments API, which carries a real principal.
    """
    if ctx.chatbot_id is None:
        return False
    async with uow_factory() as uow:
        uow.set_tenant_scope(ctx.tenant_id)
        chatbot = await uow.chatbots.get(ctx.tenant_id, ctx.chatbot_id)
    return bool(chatbot and chatbot.assistant.appointments_enabled)


class BookingPermissionGate:
    """Wraps a scheduling tool so only a booking-enabled assistant can run it.

    A wrapper rather than a check pasted into each `run`: there are seven tools
    and the one that gets forgotten is the one that leaks. The wrapper also
    keeps the gate impossible to bypass by registering a tool directly, since
    `build_scheduling_tools` is the only place they are constructed.

    `spec` is proxied unchanged, so the planner's catalogue — and every prompt
    written against it — is identical either way.
    """

    def __init__(self, tool: Any, uow_factory: UowFactory) -> None:
        self._tool = tool
        self._uow_factory = uow_factory

    @property
    def spec(self) -> ToolSpec:
        return cast("ToolSpec", self._tool.spec)

    async def run(self, ctx: ToolContext, **kwargs: Any) -> ToolResult:
        if not await _assistant_may_book(self._uow_factory, ctx):
            log.warning(
                "scheduling.booking_tool_denied",
                tenant_id=str(ctx.tenant_id),
                chatbot_id=str(ctx.chatbot_id) if ctx.chatbot_id else "",
                tool=self.spec.name,
            )
            return ToolResult(observation=BOOKING_NOT_PERMITTED, ok=False)
        return cast("ToolResult", await self._tool.run(ctx, **kwargs))


async def _resolve_reference(
    uow_factory: UowFactory, ctx: ToolContext, reference: str
) -> AppointmentId | None:
    """Turn a customer-facing reference back into an id, within this tenant.

    Scoped to the tenant's own upcoming appointments, so a guessed reference
    cannot reach another tenant's booking or a historical one.
    """
    handle = reference.strip().upper().removeprefix("APT-")
    if not handle:
        return None
    now = datetime.now(UTC)
    async with uow_factory() as uow:
        uow.set_tenant_scope(ctx.tenant_id)
        appointments = await uow.appointments.list_for_tenant(
            ctx.tenant_id,
            window_start=now,
            statuses=list(LIVE_STATUSES),
            limit=200,
        )
    for appointment in appointments:
        if appointment.id.hex[:8].upper() == handle:
            return appointment.id
    return None


class ListServicesTool:
    """What this business offers, and where.

    The agent needs real ids before it can ask about availability, and this is
    the only way it gets them — it cannot name a service the tenant does not have.
    """

    spec = ToolSpec(
        name="list_services",
        description=(
            "List the bookable services and locations for this business. "
            "Call this first to get the service_id and location_id needed by "
            "find_available_slots. Returns only active, bookable services."
        ),
        parameters={},
    )

    def __init__(self, uow_factory: UowFactory) -> None:
        self._uow_factory = uow_factory

    async def run(self, ctx: ToolContext, **kwargs: Any) -> ToolResult:
        async with self._uow_factory() as uow:
            uow.set_tenant_scope(ctx.tenant_id)
            services = await uow.services.list_for_tenant(ctx.tenant_id, active_only=True)
            locations = await uow.locations.list_for_tenant(ctx.tenant_id, active_only=True)

        bookable = [s for s in services if s.online_bookable]
        if not bookable or not locations:
            return ToolResult(
                observation=(
                    "This business has no bookable services set up yet, so no "
                    "appointment can be offered."
                ),
                data={"services": [], "locations": []},
            )

        lines = ["Services this business offers:"]
        for index, s in enumerate(bookable, start=1):
            detail = f"{s.duration_minutes} min"
            if s.category:
                detail = f"{s.category}, {detail}"
            lines.append(f"  {index}. {s.name} ({detail}) [service_id={s.id}]")
        # Said explicitly because the alternative behaviour — asking "what kind
        # of appointment would you like?" and waiting for the customer to guess
        # the catalogue — is the single thing that makes a receptionist feel like
        # a form. The tenant's own service list IS the set of options.
        if len(bookable) > 1:
            lines.append(
                "When you need to know what they want booked, offer these as a "
                "short numbered list (at most four, the most likely ones first) "
                "and let them reply with a number. Never ask them to describe it "
                "in their own words first."
            )
        else:
            lines.append(
                "There is only one service, so do not ask which one they want — "
                "say what it is and move on to finding them a time."
            )

        lines.append("Locations:")
        lines += [
            f"  - {loc.name} (location_id={loc.id}, timezone {loc.timezone})"
            for loc in locations
        ]

        return ToolResult(
            observation="\n".join(lines),
            data={
                "services": [
                    {
                        "option": index,
                        "id": str(s.id),
                        "name": s.name,
                        "category": s.category,
                        "duration_minutes": s.duration_minutes,
                    }
                    for index, s in enumerate(bookable, start=1)
                ],
                "locations": [
                    {"id": str(loc.id), "name": loc.name, "timezone": loc.timezone}
                    for loc in locations
                ],
            },
        )


class FindAvailableSlotsTool:
    """The only source of an appointment time in the whole system.

    Every slot in the observation came from the availability engine, which
    already applied working hours, buffers, notice, blocks and existing
    bookings. The agent's job is to read them out, not to reason about them.
    """

    spec = ToolSpec(
        name="find_available_slots",
        description=(
            "Find real available appointment times for a service at a location. "
            "You MUST call this before offering any time to a customer, and you "
            "may only offer times it returns — never guess or invent a slot. "
            "Give `date` as YYYY-MM-DD and optionally `time_of_day` as morning, "
            "afternoon or evening — both are read in the BRANCH's local time, so "
            "do not convert anything yourself. Omit `date` to search the next "
            "week. If a day comes back empty, try a different date."
        ),
        parameters={
            "service_id": {"type": "string", "description": "Service to book."},
            "location_id": {"type": "string", "description": "Branch to book at."},
            "date": {
                "type": "string",
                "description": "YYYY-MM-DD in the branch's local time. Omit to search a week.",
            },
            "time_of_day": {
                "type": "string",
                "description": "morning | afternoon | evening | any. Branch-local.",
            },
            "resource_id": {
                "type": "string",
                "description": "Optional specific staff member or room.",
            },
        },
    )

    def __init__(self, uow_factory: UowFactory) -> None:
        self._uow_factory = uow_factory

    async def run(self, ctx: ToolContext, **kwargs: Any) -> ToolResult:
        service_id = _parse_uuid(kwargs.get("service_id"))
        location_id = _parse_uuid(kwargs.get("location_id"))
        if service_id is None or location_id is None:
            return ToolResult(
                observation=(
                    "find_available_slots needs a valid service_id and location_id. "
                    "Call list_services first to get them."
                ),
                ok=False,
            )

        now = datetime.now(UTC)

        # The branch's timezone decides what "Monday morning" means, so it has to
        # be read before the window can be built. One extra lookup, and it is
        # what stops the agent searching the wrong eight hours of the day.
        timezone = "UTC"
        requested_day = str(kwargs.get("date") or "").strip()
        if requested_day:
            async with self._uow_factory() as uow:
                uow.set_tenant_scope(ctx.tenant_id)
                location = await uow.locations.get(ctx.tenant_id, LocationId(location_id))
            if location is None:
                return ToolResult(
                    observation="That location was not found. Call list_services again.",
                    ok=False,
                )
            timezone = location.timezone

        window = (
            _local_day_window(
                requested_day, str(kwargs.get("time_of_day") or "any"), timezone, now
            )
            if requested_day
            else None
        )
        if requested_day and window is None:
            return ToolResult(
                observation=(
                    f"{requested_day!r} is not a date I can read. Use YYYY-MM-DD."
                ),
                ok=False,
            )
        if window is not None:
            range_start, range_end = window
            if range_end <= range_start:
                # The requested part of that day is already over.
                return ToolResult(
                    observation=(
                        "That time of day has already passed. Offer a later time "
                        "today or a different date — do not invent one."
                    ),
                    data={"slots": []},
                )
        else:
            range_start = now
            range_end = now + timedelta(days=DEFAULT_SEARCH_DAYS)

        try:
            slots, location, service = await FindAvailability(
                self._uow_factory()
            ).execute(
                ctx.tenant_id,
                location_id=LocationId(location_id),
                service_id=ServiceId(service_id),
                range_start=range_start,
                range_end=range_end,
                resource_id=(
                    ResourceId(rid)
                    if (rid := _parse_uuid(kwargs.get("resource_id")))
                    else None
                ),
                limit=SLOT_QUERY_LIMIT,
                now=now,
            )
        except DomainError as exc:
            # A handled failure the planner can react to, rather than a crash.
            return ToolResult(observation=str(exc), ok=False)

        if not slots:
            return ToolResult(
                observation=(
                    f"There are no available {service.name} appointments at "
                    f"{location.name} between {range_start:%d %b %H:%M} and "
                    f"{range_end:%d %b %H:%M}. Offer a different date or service — "
                    "do not invent a time."
                ),
                data={"slots": []},
            )

        offer, alternatives = _spread_options(slots, location.timezone)

        lines = [
            f"Available {service.name} appointments at {location.name} "
            f"(times shown in {location.timezone})."
        ]
        lines.append(
            "Give the customer these as a numbered list, in exactly these words, "
            "and ask them to reply with a number:"
        )
        payload = []
        for index, slot in enumerate(offer, start=1):
            local = _in_zone(slot.starts_at, location.timezone)
            lines.append(
                f"  {index}. {_friendly(local)} (starts_at={slot.starts_at.isoformat()})"
            )
            payload.append(
                {
                    "option": index,
                    "label": _friendly(local),
                    "starts_at": slot.starts_at.isoformat(),
                    "ends_at": slot.ends_at.isoformat(),
                    "resource_ids": [str(r) for r in slot.resource_ids],
                }
            )

        if alternatives:
            # Kept behind the numbered list rather than in it: they exist so the
            # agent can answer "anything a bit later?" without another tool call,
            # not so it can read fourteen times out to someone.
            lines.append(
                "Also free, only if they ask for a different time (do not list "
                "these unprompted):"
            )
            for slot in alternatives:
                local = _in_zone(slot.starts_at, location.timezone)
                lines.append(
                    f"  - {_friendly(local)} (starts_at={slot.starts_at.isoformat()})"
                )

        lines.append(
            "Offer ONLY times from this observation. Use the exact starts_at "
            "value when holding or booking."
        )

        return ToolResult(
            observation="\n".join(lines),
            data={
                "slots": payload,
                "alternatives": [
                    {
                        "label": _friendly(_in_zone(s.starts_at, location.timezone)),
                        "starts_at": s.starts_at.isoformat(),
                    }
                    for s in alternatives
                ],
            },
        )


class CreateSlotHoldTool:
    """Hold a slot while the conversation finishes.

    On a phone call, minutes pass between "I'll take 6:15" and the details being
    captured — long enough for someone else to take it. Holding makes the slot
    genuinely unbookable by anyone else, because the hold goes through the same
    database constraint a real booking does.
    """

    spec = ToolSpec(
        name="create_slot_hold",
        description=(
            "Only for a NEW booking — never when moving an existing appointment. "
            "Temporarily reserve one of the exact times returned by "
            "find_available_slots, while you collect the customer's details. "
            "Only use a starts_at value that find_available_slots returned. "
            "If this fails, the slot was just taken: call find_available_slots "
            "again and offer what is actually left. Never tell a customer a slot "
            "is held unless this succeeds."
        ),
        parameters={
            "service_id": {"type": "string", "description": "Service to book."},
            "location_id": {"type": "string", "description": "Branch to book at."},
            "starts_at": {
                "type": "string",
                "description": "Exact ISO start time from find_available_slots.",
            },
            "resource_id": {
                "type": "string",
                "description": "Optional specific staff member or room.",
            },
        },
    )

    def __init__(self, uow_factory: UowFactory) -> None:
        self._uow_factory = uow_factory

    async def run(self, ctx: ToolContext, **kwargs: Any) -> ToolResult:
        service_id = _parse_uuid(kwargs.get("service_id"))
        location_id = _parse_uuid(kwargs.get("location_id"))
        starts_at = _parse_dt(kwargs.get("starts_at"))
        if service_id is None or location_id is None or starts_at is None:
            return ToolResult(
                observation=(
                    "create_slot_hold needs service_id, location_id and an exact "
                    "starts_at from find_available_slots."
                ),
                ok=False,
            )

        try:
            hold = await HoldSlot(self._uow_factory()).execute(
                ctx.tenant_id,
                location_id=LocationId(location_id),
                service_id=ServiceId(service_id),
                starts_at=starts_at,
                resource_id=(
                    ResourceId(rid)
                    if (rid := _parse_uuid(kwargs.get("resource_id")))
                    else None
                ),
            )
        except DomainError as exc:
            # Losing a race is a normal outcome. The planner is told what to do
            # next rather than being left to improvise.
            return ToolResult(
                observation=(
                    f"{exc} Call find_available_slots again and offer the customer "
                    "a time that is actually free."
                ),
                ok=False,
            )

        log.info(
            "scheduling.agent_held_slot",
            tenant_id=str(ctx.tenant_id),
            starts_at=hold.starts_at.isoformat(),
        )
        return ToolResult(
            observation=(
                f"Held {hold.starts_at.isoformat()} until "
                f"{hold.expires_at.isoformat()}. Hold token: {hold.token}. "
                "Confirm the customer's name and contact details next."
            ),
            data={
                "hold_token": hold.token,
                "starts_at": hold.starts_at.isoformat(),
                "ends_at": hold.ends_at.isoformat(),
                "expires_at": hold.expires_at.isoformat(),
            },
        )


class BookAppointmentTool:
    """Complete the booking. The only tool that creates a real commitment.

    Spec section 61's second half: the agent may not claim an appointment is
    booked unless the backend confirms it. That is enforced structurally — this
    tool returns an appointment reference on success and an explicit failure the
    planner must react to otherwise, and the observation text says so.

    Prefers a `hold_token` when the agent has one: converting a hold is the only
    path where the slot cannot be taken between offering it and confirming it.
    """

    spec = ToolSpec(
        name="book_appointment",
        description=(
            "Actually book the appointment. Call this ONLY after you have the "
            "customer's full name and a phone number or email, and after "
            "find_available_slots gave you the exact starts_at. Pass the "
            "hold_token from create_slot_hold if you have one. "
            "Never tell the customer their appointment is booked unless this "
            "tool returns success — if it fails, the slot was taken and you "
            "must offer them a different time."
        ),
        parameters={
            "service_id": {"type": "string", "description": "Service to book."},
            "location_id": {"type": "string", "description": "Branch to book at."},
            "starts_at": {
                "type": "string",
                "description": "Exact ISO start from find_available_slots.",
            },
            "customer_name": {"type": "string", "description": "The customer's full name."},
            "customer_phone": {"type": "string", "description": "Their phone number."},
            "customer_email": {"type": "string", "description": "Their email address."},
            "reason_for_visit": {
                "type": "string",
                "description": (
                    "What the appointment is for, in the customer's own words. "
                    "Pass whatever they told you — never ask a second time for "
                    "something they already said."
                ),
            },
            "hold_token": {
                "type": "string",
                "description": "Token from create_slot_hold, if you held the slot.",
            },
        },
    )

    def __init__(self, uow_factory: UowFactory) -> None:
        self._uow_factory = uow_factory

    async def run(self, ctx: ToolContext, **kwargs: Any) -> ToolResult:
        service_id = _parse_uuid(kwargs.get("service_id"))
        location_id = _parse_uuid(kwargs.get("location_id"))
        starts_at = _parse_dt(kwargs.get("starts_at"))
        name = str(kwargs.get("customer_name") or "").strip()
        # Falls back to the identity the channel already knows. On WhatsApp or a
        # phone call the number is not a question worth asking — the customer is
        # literally messaging from it, and asking makes the assistant look like
        # it is not paying attention.
        phone = (
            str(kwargs.get("customer_phone") or "").strip()
            or str(ctx.extras.get("customer_phone") or "").strip()
        )
        email = str(kwargs.get("customer_email") or "").strip()
        hold_token = str(kwargs.get("hold_token") or "").strip()
        # Why they are coming, carried onto the appointment so the person who
        # sees it on the day knows as much as the assistant did. Truncated to the
        # column's limit here rather than raising: losing the tail of a note is
        # not worth failing a booking the customer has already agreed to.
        reason = str(kwargs.get("reason_for_visit") or "").strip()[:MAX_NOTES]

        if service_id is None or location_id is None or starts_at is None:
            return ToolResult(
                observation=(
                    "book_appointment needs service_id, location_id and an exact "
                    "starts_at from find_available_slots."
                ),
                ok=False,
            )
        if not name:
            return ToolResult(
                observation="Ask the customer for their full name before booking.",
                ok=False,
            )
        # The channel supplies a phone for WhatsApp and voice, so this usually
        # passes. Asked for explicitly rather than assumed, because without a way
        # to reach them the appointment cannot be confirmed or reminded.
        if not phone and not email:
            return ToolResult(
                observation=(
                    "Ask the customer for a phone number or an email address — "
                    "without one we cannot send them a confirmation."
                ),
                ok=False,
            )

        # Scoped to the conversation, not just to (customer, slot): idempotency
        # protects against the same request arriving twice, and the same person
        # rebooking a slot they cancelled last week is a different request.
        conversation = str(ctx.extras.get("conversation_id") or "")
        fingerprint = (
            f"{ctx.tenant_id}:{conversation}:{service_id}:"
            f"{starts_at.isoformat()}:{phone or email}"
        )
        idempotency_key = hashlib.sha256(fingerprint.encode()).hexdigest()[:64]

        try:
            appointment, created = await BookAppointment(self._uow_factory()).execute(
                ctx.tenant_id,
                location_id=LocationId(location_id),
                service_id=ServiceId(service_id),
                starts_at=starts_at,
                customer_name=name,
                customer_phone=phone,
                customer_email=email,
                customer_notes=reason,
                hold_token=hold_token,
                source=_source_for(ctx),
                status="confirmed",
                idempotency_key=idempotency_key,
                actor_kind="ai_agent",
                actor_label="AI assistant",
                channel=str(ctx.extras.get("channel") or ""),
            )
        except DomainError as exc:
            return ToolResult(
                observation=(
                    f"The booking did NOT go through: {exc} "
                    "Tell the customer that time is no longer free, call "
                    "find_available_slots again, and offer what is actually left."
                ),
                ok=False,
            )

        local = _in_zone(appointment.starts_at, appointment.timezone)
        return ToolResult(
            observation=(
                f"{'Booked' if created else 'Already booked'}: "
                f"{appointment.customer_name} on {local:%A %d %B at %H:%M} "
                f"({appointment.timezone}). Reference {_reference(appointment.id)}. "
                "You may now confirm this to the customer."
            ),
            data={
                "appointment_id": str(appointment.id),
                "reference": _reference(appointment.id),
                "starts_at": appointment.starts_at.isoformat(),
                "status": appointment.status,
                "created": created,
            },
        )


class FindCustomerAppointmentsTool:
    """"What appointments do I have?" — looked up by the number they contacted from.

    Scoped to a phone or email rather than an id, because that is what a channel
    actually knows about whoever is talking. It returns references the other
    tools accept, so a customer never has to recite a UUID.
    """

    spec = ToolSpec(
        name="find_customer_appointments",
        description=(
            "Look up a customer's upcoming appointments by their phone number or "
            "email. Use this when someone asks about, wants to change, or wants "
            "to cancel an existing appointment. Returns a reference for each one "
            "that you pass to reschedule_appointment or cancel_appointment."
        ),
        parameters={
            "customer_phone": {"type": "string", "description": "Their phone number."},
            "customer_email": {"type": "string", "description": "Their email address."},
        },
    )

    def __init__(self, uow_factory: UowFactory) -> None:
        self._uow_factory = uow_factory

    async def run(self, ctx: ToolContext, **kwargs: Any) -> ToolResult:
        # Falls back to the identity the channel already knows, so the agent does
        # not have to ask a WhatsApp contact for the number they messaged from.
        search = (
            str(kwargs.get("customer_phone") or "").strip()
            or str(kwargs.get("customer_email") or "").strip()
            or str(ctx.extras.get("customer_phone") or "").strip()
        )
        if not search:
            return ToolResult(
                observation=(
                    "Ask the customer for the phone number or email their "
                    "appointment was booked under."
                ),
                ok=False,
            )

        now = datetime.now(UTC)
        async with self._uow_factory() as uow:
            uow.set_tenant_scope(ctx.tenant_id)
            appointments = await uow.appointments.list_for_tenant(
                ctx.tenant_id,
                window_start=now,
                search=search,
                statuses=list(LIVE_STATUSES),
                limit=10,
            )
            services = {s.id: s.name for s in await uow.services.list_for_tenant(ctx.tenant_id)}
            locations = {
                loc.id: loc.name for loc in await uow.locations.list_for_tenant(ctx.tenant_id)
            }

        if not appointments:
            return ToolResult(
                observation=(
                    f"No upcoming appointments found for {search}. Do not invent "
                    "one — offer to book a new appointment instead."
                ),
                data={"appointments": []},
            )

        lines = ["Upcoming appointments:"]
        payload = []
        for appointment in appointments:
            local = _in_zone(appointment.starts_at, appointment.timezone)
            reference = _reference(appointment.id)
            # The ids belong in the observation, not only in `data`: the loop
            # feeds the observation text back to the planner and nothing else, so
            # an id that lives only in `data` is invisible to the model. Without
            # them a reschedule cannot call find_available_slots, and the symptom
            # is the assistant reporting no availability on a day the branch is
            # open — which is what this line was originally missing.
            lines.append(
                f"- {reference}: {services.get(appointment.service_id, 'Appointment')} "
                f"at {locations.get(appointment.location_id, '')} on "
                f"{local:%A %d %B at %H:%M} ({appointment.status.replace('_', ' ')}) "
                f"[service_id={appointment.service_id} location_id={appointment.location_id}]"
            )
            payload.append(
                {
                    "reference": reference,
                    "appointment_id": str(appointment.id),
                    "starts_at": appointment.starts_at.isoformat(),
                    "service_id": str(appointment.service_id),
                    "location_id": str(appointment.location_id),
                    "status": appointment.status,
                }
            )
        return ToolResult(observation="\n".join(lines), data={"appointments": payload})


class CancelAppointmentTool:
    """Cancel, and release the slot back to the calendar."""

    spec = ToolSpec(
        name="cancel_appointment",
        description=(
            "Cancel an existing appointment. Get the reference from "
            "find_customer_appointments first. Confirm with the customer that "
            "they want to cancel before calling this — it cannot be undone. "
            "Never say an appointment is cancelled unless this returns success."
        ),
        parameters={
            "reference": {
                "type": "string",
                "description": "Reference from find_customer_appointments.",
            },
            "reason": {"type": "string", "description": "Why they are cancelling."},
        },
    )

    def __init__(self, uow_factory: UowFactory) -> None:
        self._uow_factory = uow_factory

    async def run(self, ctx: ToolContext, **kwargs: Any) -> ToolResult:
        appointment_id = await _resolve_reference(
            self._uow_factory, ctx, str(kwargs.get("reference") or "")
        )
        if appointment_id is None:
            return ToolResult(
                observation=(
                    "That reference does not match an upcoming appointment. Call "
                    "find_customer_appointments to get the right one."
                ),
                ok=False,
            )

        try:
            appointment = await TransitionAppointment(self._uow_factory()).execute(
                ctx.tenant_id,
                appointment_id,
                "cancelled",
                actor_kind="ai_agent",
                actor_label="AI assistant",
                channel=str(ctx.extras.get("channel") or ""),
                reason=str(kwargs.get("reason") or "Cancelled by customer")[:500],
            )
        except DomainError as exc:
            return ToolResult(observation=f"Could not cancel it: {exc}", ok=False)

        return ToolResult(
            observation=(
                f"Cancelled {_reference(appointment.id)}. The time is free again. "
                "You may confirm the cancellation to the customer."
            ),
            data={"appointment_id": str(appointment.id), "status": appointment.status},
        )


class RescheduleAppointmentTool:
    """Move an existing appointment, keeping its identity and its history."""

    spec = ToolSpec(
        name="reschedule_appointment",
        description=(
            "Move an existing appointment to a new time. Get the reference from "
            "find_customer_appointments, then call find_available_slots for that "
            "appointment's service to get real new times — never guess one. "
            "This is the ONLY call a reschedule needs: do NOT hold the slot "
            "first, and do NOT ask for a name, phone or email — the appointment "
            "already has them. As soon as the customer picks a time, call this. "
            "Never say an appointment has moved unless this returns success."
        ),
        parameters={
            "reference": {
                "type": "string",
                "description": "Reference from find_customer_appointments.",
            },
            "starts_at": {
                "type": "string",
                "description": "Exact new ISO start from find_available_slots.",
            },
            "reason": {"type": "string", "description": "Why they are moving it."},
        },
    )

    def __init__(self, uow_factory: UowFactory) -> None:
        self._uow_factory = uow_factory

    async def run(self, ctx: ToolContext, **kwargs: Any) -> ToolResult:
        appointment_id = await _resolve_reference(
            self._uow_factory, ctx, str(kwargs.get("reference") or "")
        )
        starts_at = _parse_dt(kwargs.get("starts_at"))
        if appointment_id is None:
            return ToolResult(
                observation=(
                    "That reference does not match an upcoming appointment. Call "
                    "find_customer_appointments to get the right one."
                ),
                ok=False,
            )
        if starts_at is None:
            return ToolResult(
                observation=(
                    "reschedule_appointment needs an exact starts_at from "
                    "find_available_slots."
                ),
                ok=False,
            )

        try:
            appointment = await RescheduleAppointment(self._uow_factory()).execute(
                ctx.tenant_id,
                appointment_id,
                starts_at=starts_at,
                actor_kind="ai_agent",
                actor_label="AI assistant",
                channel=str(ctx.extras.get("channel") or ""),
                reason=str(kwargs.get("reason") or "")[:500],
            )
        except DomainError as exc:
            return ToolResult(
                observation=(
                    f"The appointment was NOT moved: {exc} "
                    "Call find_available_slots again and offer a time that is free."
                ),
                ok=False,
            )

        local = _in_zone(appointment.starts_at, appointment.timezone)
        return ToolResult(
            observation=(
                f"Moved {_reference(appointment.id)} to {local:%A %d %B at %H:%M} "
                f"({appointment.timezone}). You may confirm this to the customer."
            ),
            data={
                "appointment_id": str(appointment.id),
                "starts_at": appointment.starts_at.isoformat(),
            },
        )


def _in_zone(moment: datetime, timezone: str) -> datetime:
    """Render a UTC instant in a branch's local time, safely.

    A branch whose zone is somehow unresolvable must not take the whole
    availability answer down with it — the UTC instant is still correct, only
    less friendly.
    """
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

    try:
        return moment.astimezone(ZoneInfo(timezone or "UTC"))
    except (ZoneInfoNotFoundError, ValueError):
        return moment


def build_scheduling_tools(uow_factory: UowFactory) -> list[Any]:
    """The appointment tools, in the order an agent naturally needs them.

    Read-only first, then the ones that change something. The ordering is not
    cosmetic: it is the order they appear in the planner's catalogue, and a
    model reads that as a rough sequence.

    Every one of them is wrapped in `BookingPermissionGate`, including the
    read-only ones — an assistant that was not given permission has no business
    reading a customer's appointments or quoting the clinic's free slots either.
    """
    return [
        BookingPermissionGate(tool, uow_factory)
        for tool in (
            ListServicesTool(uow_factory),
            FindAvailableSlotsTool(uow_factory),
            FindCustomerAppointmentsTool(uow_factory),
            CreateSlotHoldTool(uow_factory),
            BookAppointmentTool(uow_factory),
            RescheduleAppointmentTool(uow_factory),
            CancelAppointmentTool(uow_factory),
        )
    ]
