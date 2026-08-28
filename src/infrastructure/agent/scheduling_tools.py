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

import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

import structlog

from src.application.agent.tools import ToolContext, ToolResult, ToolSpec
from src.application.ports.repositories import UnitOfWork
from src.application.use_cases.availability import FindAvailability, HoldSlot
from src.domain.shared.errors import DomainError
from src.domain.shared.identifiers import LocationId, ResourceId, ServiceId

log = structlog.get_logger(__name__)

UowFactory = Callable[[], UnitOfWork]

# How far ahead a tool will look when the model does not say. A week: long
# enough to answer "when can I come in?", short enough that the observation
# stays readable in a prompt.
DEFAULT_SEARCH_DAYS = 7
# Slots per observation. A voice agent reads three or four options aloud; a
# hundred would blow the context window and help nobody.
MAX_SLOTS_IN_OBSERVATION = 8


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

        lines = ["Services:"]
        lines += [
            f"- {s.name} (service_id={s.id}, {s.duration_minutes} minutes)"
            for s in bookable
        ]
        lines.append("Locations:")
        lines += [
            f"- {loc.name} (location_id={loc.id}, timezone {loc.timezone})"
            for loc in locations
        ]

        return ToolResult(
            observation="\n".join(lines),
            data={
                "services": [
                    {
                        "id": str(s.id),
                        "name": s.name,
                        "duration_minutes": s.duration_minutes,
                    }
                    for s in bookable
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
            "Args: service_id and location_id (from list_services), optional "
            "from_date and to_date as ISO timestamps, optional resource_id to "
            "request a specific staff member."
        ),
        parameters={
            "service_id": {"type": "string", "description": "Service to book."},
            "location_id": {"type": "string", "description": "Branch to book at."},
            "from_date": {
                "type": "string",
                "description": "ISO start of the search window. Defaults to now.",
            },
            "to_date": {
                "type": "string",
                "description": "ISO end of the search window. Defaults to a week out.",
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
        range_start = _parse_dt(kwargs.get("from_date")) or now
        range_end = _parse_dt(kwargs.get("to_date")) or (
            range_start + timedelta(days=DEFAULT_SEARCH_DAYS)
        )
        if range_end <= range_start:
            range_end = range_start + timedelta(days=DEFAULT_SEARCH_DAYS)

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
                limit=MAX_SLOTS_IN_OBSERVATION,
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

        lines = [
            f"Available {service.name} appointments at {location.name} "
            f"(times shown in {location.timezone}):"
        ]
        payload = []
        for slot in slots:
            local = _in_zone(slot.starts_at, location.timezone)
            lines.append(f"- {local:%a %d %b, %H:%M} (starts_at={slot.starts_at.isoformat()})")
            payload.append(
                {
                    "starts_at": slot.starts_at.isoformat(),
                    "ends_at": slot.ends_at.isoformat(),
                    "resource_ids": [str(r) for r in slot.resource_ids],
                }
            )
        lines.append("Offer ONLY these times. Use the exact starts_at value when holding a slot.")

        return ToolResult(observation="\n".join(lines), data={"slots": payload})


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
    """The appointment tools, in the order an agent naturally needs them."""
    return [
        ListServicesTool(uow_factory),
        FindAvailableSlotsTool(uow_factory),
        CreateSlotHoldTool(uow_factory),
    ]
