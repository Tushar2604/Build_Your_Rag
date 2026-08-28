"""Booking, rescheduling, cancelling — the write side of the scheduling engine.

Every mutation here does four things in one transaction: change the appointment,
move its reservations, append a status-history row, and collect a domain event.
Keeping them together is what makes the audit trail (spec section 40) trustworthy
— there is no path that changes an appointment without recording who did it.

Concurrency is not defended here. It is defended by the exclusion constraint in
migration 0025, which `uow.reservations.reserve` surfaces as a `ConflictError`.
This module's contribution is only to make sure the reservation write and the
appointment write share a transaction, so neither can survive without the other.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import structlog

from src.application.ports.repositories import UnitOfWork
from src.application.use_cases.availability import (
    load_location_and_service,
    resolve_slot,
)
from src.domain.scheduling.availability import reservation_window
from src.domain.scheduling.entities import (
    ActorKind,
    Appointment,
    AppointmentStatus,
    BookingSource,
    StatusChange,
)
from src.domain.scheduling.events import (
    AppointmentCreated,
    AppointmentRescheduled,
    AppointmentStatusChanged,
)
from src.domain.shared.errors import ConflictError, InvalidStateError, NotFoundError
from src.domain.shared.identifiers import (
    AppointmentId,
    LocationId,
    ResourceId,
    ServiceId,
    TenantId,
    UserId,
)

log = structlog.get_logger(__name__)


class BookAppointment:
    """Turn an offered slot into a booking.

    Two ways in, and the difference matters:

      * With a `hold_token` — the caller already held the slot (a voice or chat
        conversation, where minutes pass between offer and confirmation). The
        hold is converted in place by an UPDATE, so the slot is never free for
        an instant in between.
      * Without one — a direct booking (staff creating an appointment). The slot
        is resolved through the engine and claimed in the same transaction.

    Either way the appointment row is written first and the reservation points at
    it, so a reservation can never reference an appointment that does not exist.
    """

    def __init__(self, uow: UnitOfWork) -> None:
        self._uow = uow

    async def execute(
        self,
        tenant_id: TenantId,
        *,
        location_id: LocationId,
        service_id: ServiceId,
        starts_at: datetime,
        customer_name: str,
        customer_phone: str = "",
        customer_email: str = "",
        customer_timezone: str = "",
        resource_id: ResourceId | None = None,
        hold_token: str = "",
        source: BookingSource = "staff",
        status: AppointmentStatus = "pending",
        customer_notes: str = "",
        internal_notes: str = "",
        idempotency_key: str = "",
        created_by: UserId | None = None,
        actor_kind: ActorKind = "staff",
        actor_label: str = "",
        channel: str = "",
        now: datetime | None = None,
    ) -> tuple[Appointment, bool]:
        """Returns (appointment, created). `created` is False for an idempotent
        replay, so the API can answer 200 rather than 201 and the caller can tell
        the two apart."""
        now = now or datetime.now(UTC)

        async with self._uow as uow:
            uow.set_tenant_scope(tenant_id)

            # A retry after a timeout must return the booking it already made,
            # not make a second one. Checked before any work so the common case
            # costs one indexed read.
            if idempotency_key:
                existing = await uow.appointments.get_by_idempotency_key(
                    tenant_id, idempotency_key
                )
                if existing is not None:
                    return existing, False

            location, service = await load_location_and_service(
                uow, tenant_id, location_id, service_id
            )

            if hold_token:
                held = await uow.reservations.hold_by_token(tenant_id, hold_token, now)
                if not held:
                    # Expired, already used, or never existed — all the same to
                    # the customer, who has to pick a time again.
                    raise ConflictError(
                        "That slot hold has expired. Please choose a time again."
                    )
                resource_ids = [row.resource_id for row in held]
                window_start = held[0].starts_at
                # The appointment sits inside the reserved block, past the
                # opening buffer.
                appointment_start = window_start + timedelta(
                    minutes=service.buffer_before_minutes
                )
            else:
                slot = await resolve_slot(
                    uow, tenant_id, location, service, starts_at, resource_id, now
                )
                resource_ids = list(slot.resource_ids)
                appointment_start = slot.starts_at

            appointment = Appointment(
                tenant_id=tenant_id,
                location_id=location.id,
                service_id=service.id,
                starts_at=appointment_start,
                ends_at=appointment_start + timedelta(minutes=service.duration_minutes),
                customer_name=customer_name,
                customer_phone=customer_phone,
                customer_email=customer_email,
                customer_timezone=customer_timezone,
                # Copied from the branch now, so correcting the branch's zone
                # later cannot move appointments that already happened.
                timezone=location.timezone,
                status=status,
                source=source,
                resource_ids=resource_ids,
                customer_notes=customer_notes,
                internal_notes=internal_notes,
                idempotency_key=idempotency_key,
                created_by=created_by,
            ).normalized()

            error = appointment.validation_error()
            if error:
                raise InvalidStateError(error)

            await uow.appointments.add(appointment)
            # Flushed so the reservation's foreign key has a row to point at.
            await uow.flush()

            if hold_token:
                converted = await uow.reservations.convert_hold(
                    tenant_id, hold_token, appointment.id
                )
                if not converted:
                    # The hold vanished between the read above and here. Rare,
                    # and the transaction rolls back, so nothing is left behind.
                    raise ConflictError(
                        "That slot hold has expired. Please choose a time again."
                    )
            else:
                await uow.reservations.purge_expired_holds(
                    tenant_id, resource_ids, now
                )
                await uow.reservations.reserve(
                    tenant_id,
                    resource_ids,
                    reservation_window(service, appointment_start),
                    kind="booking",
                    appointment_id=appointment.id,
                )

            # The creation itself is the first history row, so the timeline
            # starts where the appointment does rather than at its first change.
            await uow.appointments.add_status_change(
                _creation_record(appointment, actor_kind, created_by, actor_label, channel)
            )
            uow.collect_event(
                AppointmentCreated(
                    tenant_id=tenant_id,
                    appointment_id=appointment.id,
                    location_id=location.id,
                    service_id=service.id,
                    starts_at=appointment.starts_at,
                    source=source,
                    status=appointment.status,
                )
            )
            await uow.commit()

        log.info(
            "scheduling.appointment_created",
            tenant_id=str(tenant_id),
            appointment_id=str(appointment.id),
            source=source,
        )
        return appointment, True


def _creation_record(
    appointment: Appointment,
    actor_kind: ActorKind,
    actor_id: UserId | None,
    actor_label: str,
    channel: str,
) -> StatusChange:
    """The opening entry of an appointment's timeline.

    `from_status` is empty rather than a real status: nothing preceded this, and
    inventing one would make the history claim a transition that never happened.
    """
    return StatusChange(
        appointment_id=appointment.id,
        tenant_id=appointment.tenant_id,
        from_status="",
        to_status=appointment.status,
        actor_kind=actor_kind,
        actor_id=actor_id,
        actor_label=actor_label,
        channel=channel or appointment.source,
    )


class TransitionAppointment:
    """Move an appointment through its lifecycle: confirm, check in, complete,
    cancel, mark a no-show.

    One use case for every transition rather than one per verb, because they
    differ only in the target status and in whether the slot is released. The
    legality of the move itself is the domain's decision (`transition_to`).
    """

    def __init__(self, uow: UnitOfWork) -> None:
        self._uow = uow

    async def execute(
        self,
        tenant_id: TenantId,
        appointment_id: AppointmentId,
        target: AppointmentStatus,
        *,
        actor_kind: ActorKind = "staff",
        actor_id: UserId | None = None,
        actor_label: str = "",
        channel: str = "",
        reason: str = "",
        now: datetime | None = None,
    ) -> Appointment:
        now = now or datetime.now(UTC)

        async with self._uow as uow:
            uow.set_tenant_scope(tenant_id)
            appointment = await uow.appointments.get(tenant_id, appointment_id)
            if appointment is None:
                raise NotFoundError("Appointment not found.")

            # Raises InvalidStateError (422) on an illegal move, leaving the
            # appointment untouched.
            change = appointment.transition_to(
                target,
                actor_kind=actor_kind,
                actor_id=actor_id,
                actor_label=actor_label,
                channel=channel,
                reason=reason,
            )

            await uow.appointments.update(appointment)
            await uow.appointments.add_status_change(change)

            # Cancelling or marking a no-show hands the time back. Without this
            # the slot stays claimed and nobody can ever book it again.
            if not appointment.occupies_slot:
                await uow.reservations.release_for_appointment(
                    tenant_id, appointment.id, now
                )

            uow.collect_event(
                AppointmentStatusChanged(
                    tenant_id=tenant_id,
                    appointment_id=appointment.id,
                    from_status=change.from_status,
                    to_status=change.to_status,
                    actor_kind=actor_kind,
                    reason=reason,
                )
            )
            await uow.commit()

        log.info(
            "scheduling.appointment_status",
            tenant_id=str(tenant_id),
            appointment_id=str(appointment_id),
            to_status=target,
        )
        return appointment


class RescheduleAppointment:
    """Move an appointment to a new time, keeping it the same appointment.

    The old reservation is released and the new one claimed inside one
    transaction, in that order. Order matters: moving 15 minutes later reuses the
    same resource, so claiming before releasing would make the appointment
    collide with itself on the exclusion constraint. Releasing first is safe
    precisely because it is the same transaction — if the new claim loses a race,
    everything rolls back and the original booking stands.
    """

    def __init__(self, uow: UnitOfWork) -> None:
        self._uow = uow

    async def execute(
        self,
        tenant_id: TenantId,
        appointment_id: AppointmentId,
        *,
        starts_at: datetime,
        resource_id: ResourceId | None = None,
        actor_kind: ActorKind = "staff",
        actor_id: UserId | None = None,
        actor_label: str = "",
        channel: str = "",
        reason: str = "",
        now: datetime | None = None,
    ) -> Appointment:
        now = now or datetime.now(UTC)

        async with self._uow as uow:
            uow.set_tenant_scope(tenant_id)
            appointment = await uow.appointments.get(tenant_id, appointment_id)
            if appointment is None:
                raise NotFoundError("Appointment not found.")
            if appointment.is_terminal:
                raise InvalidStateError(
                    f"An appointment that is {appointment.status.replace('_', ' ')} "
                    "cannot be rescheduled."
                )

            location, service = await load_location_and_service(
                uow, tenant_id, appointment.location_id, appointment.service_id
            )

            previous_starts_at = appointment.starts_at
            if starts_at == previous_starts_at:
                raise InvalidStateError("That is already the appointment's time.")

            # Released first — see the class docstring.
            await uow.reservations.release_for_appointment(
                tenant_id, appointment.id, now
            )
            await uow.flush()

            slot = await resolve_slot(
                uow, tenant_id, location, service, starts_at, resource_id, now
            )
            await uow.reservations.purge_expired_holds(
                tenant_id, list(slot.resource_ids), now
            )
            await uow.reservations.reserve(
                tenant_id,
                list(slot.resource_ids),
                reservation_window(service, slot.starts_at),
                kind="booking",
                appointment_id=appointment.id,
            )

            appointment.starts_at = slot.starts_at
            appointment.ends_at = slot.ends_at
            appointment.resource_ids = list(slot.resource_ids)
            appointment.updated_at = now
            await uow.appointments.update(appointment)

            # A reschedule is a status-history entry too, so the timeline reads
            # as one story rather than a status trail with silent time changes.
            await uow.appointments.add_status_change(
                StatusChange(
                    appointment_id=appointment.id,
                    tenant_id=tenant_id,
                    from_status=appointment.status,
                    to_status=appointment.status,
                    actor_kind=actor_kind,
                    actor_id=actor_id,
                    actor_label=actor_label,
                    channel=channel,
                    reason=(
                        reason
                        or f"Rescheduled from {previous_starts_at.isoformat()} "
                        f"to {slot.starts_at.isoformat()}"
                    )[:500],
                )
            )
            uow.collect_event(
                AppointmentRescheduled(
                    tenant_id=tenant_id,
                    appointment_id=appointment.id,
                    previous_starts_at=previous_starts_at,
                    starts_at=slot.starts_at,
                    actor_kind=actor_kind,
                    reason=reason,
                )
            )
            await uow.commit()

        log.info(
            "scheduling.appointment_rescheduled",
            tenant_id=str(tenant_id),
            appointment_id=str(appointment_id),
        )
        return appointment


class UpdateAppointmentDetails:
    """Edit the parts of an appointment that do not move it in time.

    Kept apart from rescheduling on purpose: changing a phone number must not go
    anywhere near the reservation logic, and rescheduling must not be reachable
    by sending a `starts_at` to a general-purpose PATCH.
    """

    def __init__(self, uow: UnitOfWork) -> None:
        self._uow = uow

    async def execute(
        self,
        tenant_id: TenantId,
        appointment_id: AppointmentId,
        *,
        customer_name: str | None = None,
        customer_phone: str | None = None,
        customer_email: str | None = None,
        customer_timezone: str | None = None,
        customer_notes: str | None = None,
        internal_notes: str | None = None,
    ) -> Appointment:
        async with self._uow as uow:
            uow.set_tenant_scope(tenant_id)
            appointment = await uow.appointments.get(tenant_id, appointment_id)
            if appointment is None:
                raise NotFoundError("Appointment not found.")

            if customer_name is not None:
                appointment.customer_name = customer_name
            if customer_phone is not None:
                appointment.customer_phone = customer_phone
            if customer_email is not None:
                appointment.customer_email = customer_email
            if customer_timezone is not None:
                appointment.customer_timezone = customer_timezone
            if customer_notes is not None:
                appointment.customer_notes = customer_notes
            if internal_notes is not None:
                appointment.internal_notes = internal_notes
            appointment.updated_at = datetime.now(UTC)

            appointment = appointment.normalized()
            error = appointment.validation_error()
            if error:
                raise InvalidStateError(error)

            await uow.appointments.update(appointment)
            await uow.commit()
        return appointment


class ExpireSlotHolds:
    """Housekeeping: release holds nobody converted.

    Not what makes the system correct — the booking path purges expired holds on
    the resources it is about to claim, inside its own transaction, so a slot is
    never withheld because this has not run. This only keeps the table tidy and
    the constraint's live set small.
    """

    def __init__(self, uow: UnitOfWork, batch_size: int = 500) -> None:
        self._uow = uow
        self._batch_size = batch_size

    async def execute(self, now: datetime | None = None) -> int:
        now = now or datetime.now(UTC)
        async with self._uow as uow:
            # Deliberately not tenant-scoped: this runs from the app's own loop
            # with no request behind it, and only ever touches holds that have
            # already expired.
            released = await uow.reservations.sweep_expired(now, self._batch_size)
            await uow.commit()
        if released:
            log.info("scheduling.holds_expired", released=released)
        return released
