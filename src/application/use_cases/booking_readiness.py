"""Can this workspace's assistant book anything yet, and if not, what's missing.

Lifted out of `routers/appointments.py` when the staged navigation started
needing the same answer: "has this tenant finished setting up booking" decides
both the Appointments page's own banner and whether the shell shows the
Appointments group at all. Two implementations of that would drift, and the
half that drifts is always the one nobody is looking at.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from src.application.ports.repositories import UnitOfWork
from src.domain.shared.identifiers import TenantId


@dataclass(frozen=True)
class BookingReadiness:
    ready: bool
    locations: int = 0
    services: int = 0
    resources: int = 0
    services_with_staff: int = 0
    resources_with_hours: int = 0
    locations_with_hours: int = 0
    blockers: list[str] = field(default_factory=list)


async def compute_booking_readiness(uow: UnitOfWork, tenant_id: TenantId) -> BookingReadiness:
    """Reads the four scheduling collections and reports what still blocks a booking.

    Caller owns the transaction and the tenant scope — this only reads.
    """
    locations = await uow.locations.list_for_tenant(tenant_id)
    services = await uow.services.list_for_tenant(tenant_id)
    resources = await uow.resources.list_for_tenant(tenant_id)

    with_staff = 0
    for service in services:
        if await uow.services.eligibility_for(tenant_id, service.id):
            with_staff += 1

    with_hours = 0
    for resource in resources:
        if await uow.availability.list_rules(tenant_id, resource.id):
            with_hours += 1

    # The one that actually decides whether any slot exists. `compute_slots`
    # treats a branch with no rules as closed and returns nothing, while a
    # resource with no rules of its own simply inherits the branch's — so
    # counting only resource hours got this backwards in both directions:
    # a correctly configured workspace was reported as not ready, and one
    # with staff hours but no branch hours was reported as ready and then
    # offered no times at all.
    locations_with_hours = 0
    for location in locations:
        if await uow.availability.list_rules(tenant_id, location.id):
            locations_with_hours += 1

    blockers: list[str] = []
    # Ordered as they have to be fixed: a service cannot be given staff who do
    # not exist, and hours cannot be set on a location before there is one.
    if not locations:
        blockers.append("Add a location — the branch appointments are booked at.")
    if not services:
        blockers.append("Add a service — what people can book.")
    if not resources:
        blockers.append("Add a staff member or room under Staff & Resources.")
    if services and resources and not with_staff:
        blockers.append("Assign staff to a service — a service with nobody on it has no slots.")
    if locations and not locations_with_hours:
        blockers.append(
            "Set the location's opening hours under Availability — a branch with "
            "no hours is closed, so nothing is bookable."
        )

    return BookingReadiness(
        ready=not blockers,
        locations=len(locations),
        services=len(services),
        resources=len(resources),
        services_with_staff=with_staff,
        resources_with_hours=with_hours,
        locations_with_hours=locations_with_hours,
        blockers=blockers,
    )
