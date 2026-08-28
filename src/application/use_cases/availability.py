"""Availability lookups and slot holds — the read side of the scheduling engine.

Every channel goes through `FindAvailability`. The dashboard calendar, the
WhatsApp agent, the voice agent and the public API all get the same answer from
the same code, which is the only way spec section 61 ("the AI must never invent
a slot") can hold: there is nowhere else for a slot to come from.

The use case's job is to gather inputs and hand them to the pure engine in
`domain/scheduling/availability.py`. It deliberately contains no scheduling
arithmetic of its own.
"""

from __future__ import annotations

import secrets
from datetime import UTC, datetime, timedelta

import structlog

from src.application.ports.repositories import UnitOfWork
from src.domain.scheduling.availability import (
    AvailabilityInputs,
    AvailabilityRequest,
    Slot,
    compute_slots,
    reservation_window,
)
from src.domain.scheduling.entities import (
    DEFAULT_HOLD_TTL,
    Location,
    Resource,
    Service,
    SlotHold,
)
from src.domain.shared.errors import ConflictError, NotFoundError
from src.domain.shared.identifiers import (
    LocationId,
    ResourceId,
    ServiceId,
    TenantId,
)

log = structlog.get_logger(__name__)


def _generate_hold_token() -> str:
    """An unguessable handle for a held slot.

    Unguessable because possessing it is what lets someone convert the hold into
    a booking — the same reasoning as an interview's access token or a chatbot's
    publishable key.
    """
    return secrets.token_urlsafe(24)


async def load_availability_inputs(
    uow: UnitOfWork,
    tenant_id: TenantId,
    location: Location,
    service: Service,
    window_start: datetime,
    window_end: datetime,
    now: datetime,
) -> AvailabilityInputs:
    """Gather everything the engine needs, in four queries rather than N.

    Shared by the availability search, the hold path and the booking path so all
    three see an identical world — a hold that consulted different inputs from
    the search that produced it would be a race by construction.
    """
    eligibility = await uow.services.eligibility_for(tenant_id, service.id)
    # Optional roles are ignored in this phase: the engine requires every role it
    # is given, and offering a slot that depends on an optional resource being
    # free would be stricter than the configuration asks for.
    required = [link for link in eligibility if link.required]

    resource_ids = [link.resource_id for link in required]
    resources = {
        r.id: r for r in await uow.resources.list_by_ids(tenant_id, resource_ids)
    }

    candidates_by_role: dict[str, list[Resource]] = {}
    for link in required:
        resource = resources.get(link.resource_id)
        if resource is None or not resource.is_active:
            continue
        # A resource pinned to another branch cannot serve this one. Resources
        # with no branch (a travelling consultant, shared equipment) serve all.
        if resource.location_id is not None and resource.location_id != location.id:
            continue
        candidates_by_role.setdefault(link.role, []).append(resource)

    owner_ids = [location.id, *[r.id for r in resources.values()]]
    rules = await uow.availability.rules_for_owners(tenant_id, owner_ids)
    blocks = await uow.availability.blocks_for_owners(
        tenant_id, owner_ids, window_start, window_end
    )
    busy = await uow.reservations.busy_intervals(
        tenant_id, list(resources), window_start, window_end, now
    )

    return AvailabilityInputs(
        service=service,
        candidates_by_role=candidates_by_role,
        rules_by_owner=rules,
        blocks_by_owner=blocks,
        busy_by_resource=busy,
    )


async def load_location_and_service(
    uow: UnitOfWork,
    tenant_id: TenantId,
    location_id: LocationId,
    service_id: ServiceId,
) -> tuple[Location, Service]:
    """Both, or a 404. Scoped by tenant, so another tenant's id reads as absent
    rather than as forbidden — which is what stops an id probe confirming that
    something exists."""
    location = await uow.locations.get(tenant_id, location_id)
    if location is None:
        raise NotFoundError("Location not found.")
    service = await uow.services.get(tenant_id, service_id)
    if service is None:
        raise NotFoundError("Service not found.")
    return location, service


class FindAvailability:
    """Genuinely bookable slots for a service at a location.

    The authoritative answer. Nothing else in the system is allowed to decide
    that a time is free.
    """

    def __init__(self, uow: UnitOfWork) -> None:
        self._uow = uow

    async def execute(
        self,
        tenant_id: TenantId,
        *,
        location_id: LocationId,
        service_id: ServiceId,
        range_start: datetime,
        range_end: datetime,
        resource_id: ResourceId | None = None,
        granularity_minutes: int = 15,
        limit: int = 200,
        now: datetime | None = None,
    ) -> tuple[list[Slot], Location, Service]:
        now = now or datetime.now(UTC)
        async with self._uow as uow:
            uow.set_tenant_scope(tenant_id)
            location, service = await load_location_and_service(
                uow, tenant_id, location_id, service_id
            )
            inputs = await load_availability_inputs(
                uow, tenant_id, location, service, range_start, range_end, now
            )

        request = AvailabilityRequest(
            tenant_id=tenant_id,
            location_id=location.id,
            service_id=service.id,
            range_start=range_start,
            range_end=range_end,
            location_timezone=location.timezone,
            preferred_resource_id=resource_id,
            granularity_minutes=granularity_minutes,
            limit=limit,
        )
        return compute_slots(request, inputs, now=now), location, service


class HoldSlot:
    """Reserve a slot briefly while a customer finishes booking (section 12).

    The gap between "I'll take 3pm" and a completed booking is long enough for
    someone else to take it — on a phone call, minutes. A hold closes that gap,
    and because it is enforced by the same database constraint as a real
    booking, the slot is genuinely unbookable rather than merely marked.
    """

    def __init__(self, uow: UnitOfWork, ttl: timedelta = DEFAULT_HOLD_TTL) -> None:
        self._uow = uow
        self._ttl = ttl

    async def execute(
        self,
        tenant_id: TenantId,
        *,
        location_id: LocationId,
        service_id: ServiceId,
        starts_at: datetime,
        resource_id: ResourceId | None = None,
        now: datetime | None = None,
    ) -> SlotHold:
        now = now or datetime.now(UTC)

        async with self._uow as uow:
            uow.set_tenant_scope(tenant_id)
            location, service = await load_location_and_service(
                uow, tenant_id, location_id, service_id
            )

            # Which resources would serve this exact time is decided by the same
            # engine the search used, over a window that contains only the
            # requested start. Re-deriving it here in any other way is how a
            # hold ends up claiming a resource the search never offered.
            slot = await resolve_slot(
                uow, tenant_id, location, service, starts_at, resource_id, now
            )

            # Correctness must not wait for the housekeeping sweep: an abandoned
            # hold from ten minutes ago has to stop blocking this one now.
            await uow.reservations.purge_expired_holds(
                tenant_id, list(slot.resource_ids), now
            )

            token = _generate_hold_token()
            expires_at = now + self._ttl
            # Raises ConflictError if the slot went between the search and here.
            await uow.reservations.reserve(
                tenant_id,
                list(slot.resource_ids),
                reservation_window(service, slot.starts_at),
                kind="hold",
                hold_token=token,
                expires_at=expires_at,
            )
            await uow.commit()

        log.info(
            "scheduling.slot_held",
            tenant_id=str(tenant_id),
            starts_at=slot.starts_at.isoformat(),
            resources=len(slot.resource_ids),
        )
        return SlotHold(
            tenant_id=tenant_id,
            service_id=service.id,
            location_id=location.id,
            starts_at=slot.starts_at,
            ends_at=slot.ends_at,
            resource_ids=list(slot.resource_ids),
            expires_at=expires_at,
            token=token,
        )


class ReleaseSlotHold:
    """Give a held slot back early, when a customer abandons the booking."""

    def __init__(self, uow: UnitOfWork) -> None:
        self._uow = uow

    async def execute(self, tenant_id: TenantId, token: str) -> bool:
        now = datetime.now(UTC)
        async with self._uow as uow:
            uow.set_tenant_scope(tenant_id)
            released = await uow.reservations.release_hold(tenant_id, token, now)
            await uow.commit()
        # False for an unknown or already-expired token. Not an error: releasing
        # a hold that is already gone is the outcome the caller wanted.
        return released > 0


async def resolve_slot(
    uow: UnitOfWork,
    tenant_id: TenantId,
    location: Location,
    service: Service,
    starts_at: datetime,
    resource_id: ResourceId | None,
    now: datetime,
) -> Slot:
    """The engine's verdict on one specific start time.

    Used by both the hold and the booking paths. Asking the engine — rather than
    trusting a time the client sent — is what makes a booking request a
    confirmation of an earlier offer instead of an instruction the backend obeys.
    """
    # A window just wide enough to contain the requested start. The engine's
    # grid is anchored to the opening window, so asking for a narrow range
    # cannot shift which start times are legal.
    window_start = starts_at - timedelta(minutes=1)
    window_end = starts_at + timedelta(minutes=service.duration_minutes + 1)

    inputs = await load_availability_inputs(
        uow, tenant_id, location, service, window_start, window_end, now
    )
    request = AvailabilityRequest(
        tenant_id=tenant_id,
        location_id=location.id,
        service_id=service.id,
        range_start=window_start,
        range_end=window_end,
        location_timezone=location.timezone,
        preferred_resource_id=resource_id,
        # One minute, so the grid contains the exact requested instant whatever
        # the caller's granularity was.
        granularity_minutes=1,
        limit=64,
    )
    for slot in compute_slots(request, inputs, now=now):
        if slot.starts_at == starts_at:
            return slot

    raise ConflictError(
        "That time isn't available. Please choose another slot."
    )
