"""Appointments and slot holds — the write surface of the scheduling engine.

Two things are worth knowing about this router:

  * It never decides that a time is free. Booking resolves the requested start
    through the availability engine, and the database's exclusion constraint has
    the final word. A 409 here means someone else got the slot first, which is a
    normal outcome rather than an error.
  * Every state change goes through `TransitionAppointment`, so there is no path
    that moves an appointment without writing who moved it and why.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Header, HTTPException, Query, Response

from src.application.ports.repositories import UnitOfWork
from src.application.use_cases.appointments import (
    BookAppointment,
    RescheduleAppointment,
    TransitionAppointment,
    UpdateAppointmentDetails,
)
from src.application.use_cases.availability import HoldSlot, ReleaseSlotHold
from src.config.container import Container
from src.config.settings import get_settings
from src.domain.scheduling.entities import (
    ALL_STATUSES,
    Appointment,
    AppointmentStatus,
    Location,
    Resource,
    Service,
)
from src.domain.shared.identifiers import (
    AppointmentId,
    LocationId,
    ResourceId,
    ServiceId,
    TenantId,
)
from src.interfaces.api.deps import ContainerDep, Principal, PrincipalDep
from src.interfaces.api.schemas import (
    AppointmentActionRequest,
    AppointmentHistoryEntry,
    AppointmentHistoryResponse,
    AppointmentPageResponse,
    AppointmentResponse,
    AppointmentSummaryResponse,
    BookingReadinessResponse,
    CreateAppointmentRequest,
    NewAppointmentsResponse,
    RescheduleAppointmentRequest,
    SlotHoldRequest,
    SlotHoldResponse,
    UpdateAppointmentRequest,
)

router = APIRouter(tags=["appointments"])

_MAX_PAGE_SIZE = 200


async def _to_response(
    uow: UnitOfWork, tenant_id: TenantId, appointment: Appointment
) -> AppointmentResponse:
    """Add the labels a calendar needs so rendering is one request, not four."""
    location = await uow.locations.get(tenant_id, appointment.location_id)
    service = await uow.services.get(tenant_id, appointment.service_id)
    resources = await uow.resources.list_by_ids(tenant_id, appointment.resource_ids)
    return _build_response(appointment, location, service, resources)


def _build_response(
    appointment: Appointment,
    location: Location | None,
    service: Service | None,
    resources: list[Resource],
) -> AppointmentResponse:
    by_id = {r.id: r.name for r in resources}
    return AppointmentResponse(
        id=appointment.id,
        location_id=appointment.location_id,
        service_id=appointment.service_id,
        starts_at=appointment.starts_at,
        ends_at=appointment.ends_at,
        timezone=appointment.timezone,
        status=appointment.status,
        source=appointment.source,
        customer_name=appointment.customer_name,
        customer_phone=appointment.customer_phone,
        customer_email=appointment.customer_email,
        customer_timezone=appointment.customer_timezone,
        resource_ids=list(appointment.resource_ids),
        customer_notes=appointment.customer_notes,
        internal_notes=appointment.internal_notes,
        cancellation_reason=appointment.cancellation_reason,
        rescheduled_from_id=appointment.rescheduled_from_id,
        location_name=location.name if location else "",
        service_name=service.name if service else "",
        # Ordered to match `resource_ids`, so the two lists line up in the UI.
        resource_names=[by_id.get(r, "") for r in appointment.resource_ids],
        created_at=appointment.created_at,
        updated_at=appointment.updated_at,
    )


# --- Slot holds -------------------------------------------------------------


@router.post("/slot-holds", response_model=SlotHoldResponse, status_code=201)
async def create_slot_hold(
    body: SlotHoldRequest,
    principal: PrincipalDep,
    container: ContainerDep,
) -> SlotHoldResponse:
    """Claim a slot briefly while a customer decides (spec section 12).

    Returns 409 when the slot has already gone. That is the database's exclusion
    constraint answering, not an optimistic pre-check.
    """
    ttl = timedelta(minutes=get_settings().slot_hold_ttl_minutes)
    hold = await HoldSlot(container.unit_of_work(), ttl=ttl).execute(
        principal.tenant_id,
        location_id=LocationId(body.location_id),
        service_id=ServiceId(body.service_id),
        starts_at=body.starts_at,
        resource_id=ResourceId(body.resource_id) if body.resource_id else None,
    )
    return SlotHoldResponse(
        token=hold.token,
        starts_at=hold.starts_at,
        ends_at=hold.ends_at,
        expires_at=hold.expires_at,
        resource_ids=list(hold.resource_ids),
    )


@router.delete("/slot-holds/{token}", status_code=204)
async def release_slot_hold(
    token: str,
    principal: PrincipalDep,
    container: ContainerDep,
) -> None:
    """Give a held slot back early. Releasing an unknown or expired token is a
    success — the caller wanted the hold gone, and it is."""
    await ReleaseSlotHold(container.unit_of_work()).execute(principal.tenant_id, token)


# --- Appointments -----------------------------------------------------------


@router.get("/appointments", response_model=AppointmentPageResponse)
async def list_appointments(
    principal: PrincipalDep,
    container: ContainerDep,
    range_start: datetime | None = None,
    range_end: datetime | None = None,
    location_id: uuid.UUID | None = None,
    service_id: uuid.UUID | None = None,
    resource_id: uuid.UUID | None = None,
    status: str = "",
    search: str = Query("", max_length=120),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=_MAX_PAGE_SIZE),
) -> AppointmentPageResponse:
    statuses = [s.strip() for s in status.split(",") if s.strip()]
    unknown = [s for s in statuses if s not in ALL_STATUSES]
    if unknown:
        raise HTTPException(
            status_code=422, detail=f"Unknown status: {', '.join(unknown)}"
        )

    offset = (page - 1) * page_size
    async with container.unit_of_work() as uow:
        uow.set_tenant_scope(principal.tenant_id)
        appointments = await uow.appointments.list_for_tenant(
            principal.tenant_id,
            window_start=range_start,
            window_end=range_end,
            location_id=LocationId(location_id) if location_id else None,
            service_id=ServiceId(service_id) if service_id else None,
            resource_id=ResourceId(resource_id) if resource_id else None,
            statuses=statuses or None,
            search=search,
            limit=page_size,
            offset=offset,
        )
        # Labels resolved once for the whole page rather than per appointment.
        locations = {
            loc.id: loc for loc in await uow.locations.list_for_tenant(principal.tenant_id)
        }
        services = {
            svc.id: svc for svc in await uow.services.list_for_tenant(principal.tenant_id)
        }
        resources = await uow.resources.list_for_tenant(principal.tenant_id)

    items = [
        _build_response(
            a, locations.get(a.location_id), services.get(a.service_id), resources
        )
        for a in appointments
    ]
    return AppointmentPageResponse(
        appointments=items,
        # A full count would be a second aggregate over the same filters on
        # every keystroke of the search box. The page length is what the UI
        # needs to decide whether a "next" button is live.
        total=offset + len(items),
        page=page,
        page_size=page_size,
    )


@router.get("/appointments/readiness", response_model=BookingReadinessResponse)
async def booking_readiness(
    principal: PrincipalDep, container: ContainerDep
) -> BookingReadinessResponse:
    """Can this workspace's assistant book anything yet, and if not, what next.

    Exists because the failure is silent from the outside. With no opening
    hours, availability search returns an empty list, the assistant says "no
    times available" — which is true and useless — and the operator concludes
    booking is broken. This turns that into a list of what is missing.
    """
    async with container.unit_of_work() as uow:
        uow.set_tenant_scope(principal.tenant_id)
        locations = await uow.locations.list_for_tenant(principal.tenant_id)
        services = await uow.services.list_for_tenant(principal.tenant_id)
        resources = await uow.resources.list_for_tenant(principal.tenant_id)
        with_staff = 0
        for service in services:
            linked = await uow.services.eligibility_for(principal.tenant_id, service.id)
            if linked:
                with_staff += 1
        with_hours = 0
        for resource in resources:
            rules = await uow.availability.list_rules(principal.tenant_id, resource.id)
            if rules:
                with_hours += 1

    blockers: list[str] = []
    # Ordered as they have to be fixed: a service cannot be given staff who do
    # not exist, and staff cannot be given hours before they exist.
    if not locations:
        blockers.append("Add a location — the branch appointments are booked at.")
    if not services:
        blockers.append("Add a service — what people can book.")
    if not resources:
        blockers.append("Add a staff member or room under Staff & Resources.")
    if services and resources and not with_staff:
        blockers.append("Assign staff to a service — a service with nobody on it has no slots.")
    if resources and not with_hours:
        blockers.append("Set opening hours under Availability — without them nothing is bookable.")

    return BookingReadinessResponse(
        ready=not blockers,
        locations=len(locations),
        services=len(services),
        resources=len(resources),
        services_with_staff=with_staff,
        resources_with_hours=with_hours,
        blockers=blockers,
    )


@router.get("/appointments/new", response_model=NewAppointmentsResponse)
async def new_appointments(
    principal: PrincipalDep,
    container: ContainerDep,
    since: datetime | None = None,
) -> NewAppointmentsResponse:
    """The badge count: bookings taken since `since`.

    Its own endpoint rather than a field on `/appointments/summary` because the
    two are asked on completely different schedules — the summary is read when
    someone opens the page, this is polled by the sidebar on every screen, and
    it has to stay cheap enough to do that.

    `since` is supplied by the client, which is what makes the badge per-person:
    "new to me" is a fact about who is looking, and the alternative — a
    server-side seen marker — would mean one colleague clearing the badge for
    everybody.
    """
    # A missing watermark means a browser that has never looked. Counting from
    # the last day rather than from all time: a workspace with a year of
    # bookings would otherwise open with a badge in the hundreds, which teaches
    # people to ignore it on their first day.
    watermark = since or (datetime.now(UTC) - timedelta(days=1))
    if watermark.tzinfo is None:
        watermark = watermark.replace(tzinfo=UTC)

    async with container.unit_of_work() as uow:
        uow.set_tenant_scope(principal.tenant_id)
        count = await uow.appointments.count_booked_since(principal.tenant_id, watermark)
        latest = None
        if count:
            recent = await uow.appointments.list_for_tenant(
                principal.tenant_id, limit=1, offset=0
            )
            latest = max((a.created_at for a in recent), default=None)
    return NewAppointmentsResponse(count=count, since=watermark, latest_at=latest)


@router.get("/appointments/summary", response_model=AppointmentSummaryResponse)
async def appointment_summary(
    principal: PrincipalDep,
    container: ContainerDep,
    range_start: datetime | None = None,
    range_end: datetime | None = None,
) -> AppointmentSummaryResponse:
    """Status tallies for the dashboard, counted in the database.

    Registered before `/appointments/{appointment_id}` so "summary" is a page
    rather than an id that fails to parse as a UUID.
    """
    now = datetime.now(UTC)
    start = range_start or now.replace(hour=0, minute=0, second=0, microsecond=0)
    end = range_end or start + timedelta(days=1)
    if end <= start:
        raise HTTPException(status_code=422, detail="range_end must be after range_start")

    async with container.unit_of_work() as uow:
        uow.set_tenant_scope(principal.tenant_id)
        by_status = await uow.appointments.counts_by_status(
            principal.tenant_id, start, end
        )
    return AppointmentSummaryResponse(
        window_start=start,
        window_end=end,
        total=sum(by_status.values()),
        by_status=by_status,
    )


@router.post("/appointments", response_model=AppointmentResponse, status_code=201)
async def create_appointment(
    body: CreateAppointmentRequest,
    principal: PrincipalDep,
    container: ContainerDep,
    response: Response,
    idempotency_key: str = Header(default="", alias="Idempotency-Key"),
) -> AppointmentResponse:
    """Book an appointment.

    409 means the slot went to someone else between the search and this call —
    the expected outcome of a race, not a failure. The client should re-query
    availability and offer the customer what is actually left.

    An `Idempotency-Key` header (or the body field) makes a retry safe: the same
    key returns the booking it already made, with 200 instead of 201.
    """
    key = (idempotency_key or body.idempotency_key).strip()[:128]

    appointment, created = await BookAppointment(container.unit_of_work()).execute(
        principal.tenant_id,
        location_id=LocationId(body.location_id),
        service_id=ServiceId(body.service_id),
        starts_at=body.starts_at,
        customer_name=body.customer_name,
        customer_phone=body.customer_phone,
        customer_email=body.customer_email,
        customer_timezone=body.customer_timezone,
        resource_id=ResourceId(body.resource_id) if body.resource_id else None,
        hold_token=body.hold_token,
        source=body.source,
        status=body.status,
        customer_notes=body.customer_notes,
        internal_notes=body.internal_notes,
        idempotency_key=key,
        created_by=principal.user_id,
        actor_kind="staff",
        channel="dashboard",
    )
    # 200 for a replay so a client can tell "I made this" from "I already had it".
    response.status_code = 201 if created else 200

    async with container.unit_of_work() as uow:
        uow.set_tenant_scope(principal.tenant_id)
        return await _to_response(uow, principal.tenant_id, appointment)


@router.get("/appointments/{appointment_id}", response_model=AppointmentResponse)
async def get_appointment(
    appointment_id: uuid.UUID,
    principal: PrincipalDep,
    container: ContainerDep,
) -> AppointmentResponse:
    async with container.unit_of_work() as uow:
        uow.set_tenant_scope(principal.tenant_id)
        appointment = await uow.appointments.get(
            principal.tenant_id, AppointmentId(appointment_id)
        )
        if appointment is None:
            # 404 rather than 403 for another tenant's id: a 403 would confirm
            # that the appointment exists.
            raise HTTPException(status_code=404, detail="Appointment not found")
        return await _to_response(uow, principal.tenant_id, appointment)


@router.patch("/appointments/{appointment_id}", response_model=AppointmentResponse)
async def update_appointment(
    appointment_id: uuid.UUID,
    body: UpdateAppointmentRequest,
    principal: PrincipalDep,
    container: ContainerDep,
) -> AppointmentResponse:
    """Edit details only. Moving an appointment in time goes through
    /reschedule, so this can never reach the reservation logic."""
    appointment = await UpdateAppointmentDetails(container.unit_of_work()).execute(
        principal.tenant_id,
        AppointmentId(appointment_id),
        customer_name=body.customer_name,
        customer_phone=body.customer_phone,
        customer_email=body.customer_email,
        customer_timezone=body.customer_timezone,
        customer_notes=body.customer_notes,
        internal_notes=body.internal_notes,
    )
    async with container.unit_of_work() as uow:
        uow.set_tenant_scope(principal.tenant_id)
        return await _to_response(uow, principal.tenant_id, appointment)


@router.get(
    "/appointments/{appointment_id}/history", response_model=AppointmentHistoryResponse
)
async def appointment_history(
    appointment_id: uuid.UUID,
    principal: PrincipalDep,
    container: ContainerDep,
) -> AppointmentHistoryResponse:
    """The audit trail: who changed this, when, through which channel, and why."""
    async with container.unit_of_work() as uow:
        uow.set_tenant_scope(principal.tenant_id)
        appointment = await uow.appointments.get(
            principal.tenant_id, AppointmentId(appointment_id)
        )
        if appointment is None:
            raise HTTPException(status_code=404, detail="Appointment not found")
        entries = await uow.appointments.history(
            principal.tenant_id, AppointmentId(appointment_id)
        )
    return AppointmentHistoryResponse(
        appointment_id=appointment_id,
        entries=[
            AppointmentHistoryEntry(
                from_status=e.from_status,
                to_status=e.to_status,
                actor_kind=e.actor_kind,
                actor_label=e.actor_label,
                channel=e.channel,
                reason=e.reason,
                occurred_at=e.occurred_at,
            )
            for e in entries
        ],
    )


@router.post(
    "/appointments/{appointment_id}/reschedule", response_model=AppointmentResponse
)
async def reschedule_appointment(
    appointment_id: uuid.UUID,
    body: RescheduleAppointmentRequest,
    principal: PrincipalDep,
    container: ContainerDep,
) -> AppointmentResponse:
    """Move an appointment, keeping its identity and its history.

    The old reservation is released and the new one claimed in one transaction,
    so a lost race leaves the original booking exactly as it was.
    """
    appointment = await RescheduleAppointment(container.unit_of_work()).execute(
        principal.tenant_id,
        AppointmentId(appointment_id),
        starts_at=body.starts_at,
        resource_id=ResourceId(body.resource_id) if body.resource_id else None,
        actor_kind="staff",
        actor_id=principal.user_id,
        channel="dashboard",
        reason=body.reason,
    )
    async with container.unit_of_work() as uow:
        uow.set_tenant_scope(principal.tenant_id)
        return await _to_response(uow, principal.tenant_id, appointment)


async def _transition(
    appointment_id: uuid.UUID,
    target: AppointmentStatus,
    principal: Principal,
    container: Container,
    reason: str,
) -> AppointmentResponse:
    """Shared body for the lifecycle endpoints below.

    They differ only in target status, so the alternative is five copies of the
    same six lines — and five places for the audit record to be forgotten.
    """
    appointment = await TransitionAppointment(container.unit_of_work()).execute(
        principal.tenant_id,
        AppointmentId(appointment_id),
        target,
        actor_kind="staff",
        actor_id=principal.user_id,
        channel="dashboard",
        reason=reason,
    )
    async with container.unit_of_work() as uow:
        uow.set_tenant_scope(principal.tenant_id)
        return await _to_response(uow, principal.tenant_id, appointment)


@router.post("/appointments/{appointment_id}/confirm", response_model=AppointmentResponse)
async def confirm_appointment(
    appointment_id: uuid.UUID,
    principal: PrincipalDep,
    container: ContainerDep,
    body: AppointmentActionRequest | None = None,
) -> AppointmentResponse:
    return await _transition(
        appointment_id, "confirmed", principal, container, body.reason if body else ""
    )


@router.post("/appointments/{appointment_id}/check-in", response_model=AppointmentResponse)
async def check_in_appointment(
    appointment_id: uuid.UUID,
    principal: PrincipalDep,
    container: ContainerDep,
    body: AppointmentActionRequest | None = None,
) -> AppointmentResponse:
    return await _transition(
        appointment_id, "checked_in", principal, container, body.reason if body else ""
    )


@router.post("/appointments/{appointment_id}/start", response_model=AppointmentResponse)
async def start_appointment(
    appointment_id: uuid.UUID,
    principal: PrincipalDep,
    container: ContainerDep,
    body: AppointmentActionRequest | None = None,
) -> AppointmentResponse:
    return await _transition(
        appointment_id, "in_progress", principal, container, body.reason if body else ""
    )


@router.post("/appointments/{appointment_id}/complete", response_model=AppointmentResponse)
async def complete_appointment(
    appointment_id: uuid.UUID,
    principal: PrincipalDep,
    container: ContainerDep,
    body: AppointmentActionRequest | None = None,
) -> AppointmentResponse:
    return await _transition(
        appointment_id, "completed", principal, container, body.reason if body else ""
    )


@router.post("/appointments/{appointment_id}/cancel", response_model=AppointmentResponse)
async def cancel_appointment(
    appointment_id: uuid.UUID,
    principal: PrincipalDep,
    container: ContainerDep,
    body: AppointmentActionRequest | None = None,
) -> AppointmentResponse:
    """Cancel, releasing the slot back to the calendar."""
    return await _transition(
        appointment_id, "cancelled", principal, container, body.reason if body else ""
    )


@router.post("/appointments/{appointment_id}/no-show", response_model=AppointmentResponse)
async def mark_no_show(
    appointment_id: uuid.UUID,
    principal: PrincipalDep,
    container: ContainerDep,
    body: AppointmentActionRequest | None = None,
) -> AppointmentResponse:
    return await _transition(
        appointment_id, "no_show", principal, container, body.reason if body else ""
    )
