"""Make a workspace genuinely bookable the moment an assistant is told to book.

Turning `appointments_enabled` on used to be a promise the backend could not
keep. The assistant gained the booking tools, but a workspace that had never
opened the Scheduling screens had no location, no service, no staff and no
opening hours — so `find_available_slots` correctly returned nothing, and the
receptionist told every customer there was no availability. From the outside
that reads as "booking is broken", because nothing says which of five separate
screens still needs filling in.

So enabling booking provisions what is missing, and nothing else:

  * Each piece is filled **only if it is absent**. An operator who already has a
    location and a service gets the staff member and the hours they are missing,
    and their own configuration is never touched.
  * Everything created is ordinary, editable configuration — the same rows the
    Scheduling screens write. There is no hidden "default" mode to unpick later;
    renaming the seeded service is all it takes to own it.
  * It is idempotent. Flipping the toggle off and on, or enabling a second
    assistant, adds nothing the second time.

The one judgement call it makes is the opening hours, because a location with no
hours is *closed* as far as the availability engine is concerned — that single
missing row is the difference between a working receptionist and one that
apologises all day.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import time

import structlog

from src.application.ports.repositories import UnitOfWork
from src.domain.scheduling.entities import (
    AvailabilityRule,
    Location,
    Resource,
    Service,
    ServiceResource,
)
from src.domain.shared.identifiers import TenantId

log = structlog.get_logger(__name__)

# Monday-to-Saturday, 9 to 6. Deliberately unremarkable: the point is that the
# calendar is open at all, and every one of these is editable on the
# Availability screen the moment the operator disagrees.
DEFAULT_OPEN_WEEKDAYS: tuple[int, ...] = (0, 1, 2, 3, 4, 5)
DEFAULT_OPEN_FROM = time(9, 0)
DEFAULT_OPEN_UNTIL = time(18, 0)

DEFAULT_SERVICE_NAME = "Consultation"
DEFAULT_SERVICE_MINUTES = 30
DEFAULT_RESOURCE_NAME = "Available staff"


@dataclass
class BookingSetupReport:
    """What had to be created, in operator-readable words.

    Returned rather than only logged, so the UI can say what just appeared under
    Scheduling. Silently creating rows an operator later finds and cannot
    explain is its own kind of bug.
    """

    created: list[str] = field(default_factory=list)
    location_timezone: str = ""

    @property
    def changed(self) -> bool:
        return bool(self.created)


class EnsureBookingSetup:
    """Fill in whatever a workspace is missing before it can take a booking."""

    def __init__(self, uow: UnitOfWork) -> None:
        self._uow = uow

    async def execute(
        self, tenant_id: TenantId, *, timezone: str = "UTC"
    ) -> BookingSetupReport:
        report = BookingSetupReport()

        async with self._uow as uow:
            uow.set_tenant_scope(tenant_id)

            locations = await uow.locations.list_for_tenant(tenant_id)
            services = await uow.services.list_for_tenant(tenant_id)
            resources = await uow.resources.list_for_tenant(tenant_id)

            # --- Where appointments happen ---
            location = next((loc for loc in locations if loc.is_active), None)
            if location is None:
                tenant = await uow.tenants.get(tenant_id)
                location = Location(
                    tenant_id=tenant_id,
                    name=(tenant.name if tenant else "") or "Main location",
                    timezone=timezone or "UTC",
                ).normalized()
                if location.validation_error():
                    # An unresolvable configured zone must not stop the seed:
                    # UTC hours are wrong by an offset, no hours at all are
                    # wrong by everything.
                    location.timezone = "UTC"
                await uow.locations.add(location)
                report.created.append(f"Location '{location.name}'")
            report.location_timezone = location.timezone

            # --- What can be booked ---
            service = next(
                (s for s in services if s.is_active and s.online_bookable), None
            )
            if service is None:
                service = Service(
                    tenant_id=tenant_id,
                    name=DEFAULT_SERVICE_NAME,
                    duration_minutes=DEFAULT_SERVICE_MINUTES,
                    description="General appointment. Rename it, or add more, under Services.",
                ).normalized()
                await uow.services.add(service)
                report.created.append(
                    f"Service '{service.name}' ({service.duration_minutes} min)"
                )

            # --- Who serves it ---
            servable = [
                r
                for r in resources
                if r.is_active and (r.location_id is None or r.location_id == location.id)
            ]
            resource = next(iter(servable), None)
            if resource is None:
                resource = Resource(
                    tenant_id=tenant_id,
                    name=DEFAULT_RESOURCE_NAME,
                    kind="staff",
                    location_id=location.id,
                ).normalized()
                await uow.resources.add(resource)
                report.created.append(f"Staff member '{resource.name}'")

            # Eligibility carries their ids, so the rows have to exist first.
            await uow.flush()

            # --- The link between them ---
            # Written only when the service has no eligibility at all. A service
            # deliberately restricted to one practitioner must not quietly gain
            # another.
            eligibility = await uow.services.eligibility_for(tenant_id, service.id)
            if not eligibility:
                await uow.services.set_eligibility(
                    tenant_id,
                    service.id,
                    [
                        ServiceResource(
                            tenant_id=tenant_id,
                            service_id=service.id,
                            resource_id=resource.id,
                            role="primary",
                            required=True,
                        )
                    ],
                )
                report.created.append(f"'{resource.name}' assigned to '{service.name}'")

            # --- When it is open ---
            # Location hours, not resource hours: `compute_slots` treats a branch
            # with no rules as closed, and a resource with no rules of its own
            # inherits the branch's. One set of rows makes both true.
            rules = await uow.availability.list_rules(tenant_id, location.id)
            if not rules:
                for weekday in DEFAULT_OPEN_WEEKDAYS:
                    await uow.availability.add_rule(
                        AvailabilityRule(
                            tenant_id=tenant_id,
                            owner_kind="location",
                            owner_id=location.id,
                            weekday=weekday,
                            start_time=DEFAULT_OPEN_FROM,
                            end_time=DEFAULT_OPEN_UNTIL,
                        )
                    )
                report.created.append(
                    f"Opening hours Mon-Sat {DEFAULT_OPEN_FROM:%H:%M}-"
                    f"{DEFAULT_OPEN_UNTIL:%H:%M} ({location.timezone})"
                )

            await uow.commit()

        if report.changed:
            log.info(
                "scheduling.booking_setup_seeded",
                tenant_id=str(tenant_id),
                created=report.created,
            )
        return report
