"""Appointment status transitions and entity validation (spec sections 7, 8, 40).

The transition table is the product's guarantee that history means something: a
cancelled appointment cannot quietly become completed, and every legal move
leaves a record naming who made it. Both halves are tested here.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, time, timedelta

import pytest
from src.domain.scheduling.entities import (
    ALL_STATUSES,
    DEFAULT_HOLD_TTL,
    RELEASING_STATUSES,
    TERMINAL_STATUSES,
    Appointment,
    AvailabilityRule,
    BlockedPeriod,
    Location,
    Resource,
    Service,
    SlotHold,
    can_transition,
    is_valid_timezone,
)
from src.domain.shared.errors import InvalidStateError
from src.domain.shared.identifiers import (
    LocationId,
    ResourceId,
    ServiceId,
    TenantId,
    new_id,
)

TENANT = TenantId(new_id())
START = datetime(2026, 3, 2, 9, 0, tzinfo=UTC)


def _appointment(**overrides: object) -> Appointment:
    defaults: dict[str, object] = {
        "tenant_id": TENANT,
        "location_id": LocationId(new_id()),
        "service_id": ServiceId(new_id()),
        "starts_at": START,
        "ends_at": START + timedelta(minutes=30),
        "customer_name": "Mohammed Ali",
        "customer_phone": "+971501234567",
    }
    defaults.update(overrides)
    return Appointment(**defaults)  # type: ignore[arg-type]


class TestTheHappyPath:
    def test_an_appointment_walks_from_pending_to_completed(self) -> None:
        appointment = _appointment()
        for target in ("confirmed", "arrived", "checked_in", "in_progress", "completed"):
            appointment.transition_to(target, actor_kind="staff")  # type: ignore[arg-type]
        assert appointment.status == "completed"
        assert appointment.is_terminal

    def test_every_transition_returns_a_history_row_naming_the_actor(self) -> None:
        appointment = _appointment()
        actor = uuid.uuid4()
        change = appointment.transition_to(
            "confirmed",
            actor_kind="customer",
            actor_id=actor,
            actor_label="Mohammed Ali",
            channel="whatsapp",
            reason="Replied YES",
        )
        assert (change.from_status, change.to_status) == ("pending", "confirmed")
        assert change.actor_kind == "customer"
        assert change.actor_id == actor
        assert change.channel == "whatsapp"
        assert change.appointment_id == appointment.id
        assert change.tenant_id == appointment.tenant_id

    def test_a_cancellation_reason_is_kept_on_the_appointment(self) -> None:
        # The reason has to survive on the row, not only in history: the list
        # view shows it without joining.
        appointment = _appointment()
        appointment.transition_to(
            "cancelled", actor_kind="customer", reason="Feeling better"
        )
        assert appointment.cancellation_reason == "Feeling better"


class TestIllegalTransitions:
    def test_a_cancelled_appointment_cannot_be_completed(self) -> None:
        appointment = _appointment()
        appointment.transition_to("cancelled", actor_kind="staff")
        with pytest.raises(InvalidStateError):
            appointment.transition_to("completed", actor_kind="staff")

    def test_a_completed_appointment_cannot_be_reopened(self) -> None:
        appointment = _appointment(status="confirmed")
        appointment.transition_to("completed", actor_kind="staff")
        for target in ("in_progress", "confirmed", "cancelled"):
            with pytest.raises(InvalidStateError):
                appointment.transition_to(target, actor_kind="staff")  # type: ignore[arg-type]

    def test_a_no_show_cannot_walk_back_into_the_room(self) -> None:
        appointment = _appointment(status="confirmed")
        appointment.transition_to("no_show", actor_kind="system")
        with pytest.raises(InvalidStateError):
            appointment.transition_to("checked_in", actor_kind="staff")

    def test_transitioning_to_the_current_status_is_rejected(self) -> None:
        # Otherwise a double-tapped Confirm button writes a meaningless
        # confirmed -> confirmed row into the audit trail.
        appointment = _appointment(status="confirmed")
        with pytest.raises(InvalidStateError):
            appointment.transition_to("confirmed", actor_kind="staff")

    def test_a_rejected_transition_leaves_the_status_untouched(self) -> None:
        appointment = _appointment(status="completed")
        with pytest.raises(InvalidStateError):
            appointment.transition_to("cancelled", actor_kind="staff")
        assert appointment.status == "completed"

    def test_every_terminal_status_is_genuinely_terminal(self) -> None:
        for status in TERMINAL_STATUSES:
            assert not any(can_transition(status, target) for target in ALL_STATUSES)


class TestSlotOccupancy:
    def test_a_live_appointment_holds_its_slot(self) -> None:
        for status in ("pending", "confirmed", "checked_in", "in_progress", "completed"):
            assert _appointment(status=status).occupies_slot

    def test_a_cancelled_or_rescheduled_appointment_releases_its_slot(self) -> None:
        # The failure this guards: a cancelled appointment that keeps its
        # reservation, leaving the slot dead and unbookable forever.
        for status in RELEASING_STATUSES:
            assert not _appointment(status=status).occupies_slot


class TestValidation:
    def test_a_customer_needs_a_way_to_be_contacted(self) -> None:
        appointment = _appointment(customer_phone="", customer_email="")
        assert "phone number or an email" in (appointment.validation_error() or "")

    def test_either_a_phone_or_an_email_is_enough(self) -> None:
        assert _appointment(customer_phone="", customer_email="a@b.com").validation_error() is None
        assert _appointment(customer_phone="+971500000000").validation_error() is None

    def test_an_appointment_must_end_after_it_starts(self) -> None:
        appointment = _appointment(ends_at=START - timedelta(minutes=1))
        assert "end after it starts" in (appointment.validation_error() or "")

    def test_an_unknown_booking_source_is_rejected(self) -> None:
        assert _appointment(source="carrier_pigeon").validation_error() is not None

    def test_an_unknown_timezone_is_rejected(self) -> None:
        assert _appointment(timezone="Mars/Olympus").validation_error() is not None
        assert _appointment(timezone="Asia/Dubai").validation_error() is None

    def test_duration_is_derived_from_the_stored_instants(self) -> None:
        assert _appointment().duration_minutes == 30


class TestServiceRules:
    def test_the_reserved_block_includes_both_buffers(self) -> None:
        service = Service(
            tenant_id=TENANT,
            name="Consultation",
            duration_minutes=30,
            buffer_before_minutes=5,
            buffer_after_minutes=10,
        )
        assert service.total_block_minutes == 45

    def test_a_deposit_cannot_exceed_the_price(self) -> None:
        service = Service(
            tenant_id=TENANT,
            name="Consultation",
            duration_minutes=30,
            price_cents=25_000,
            deposit_cents=30_000,
        )
        assert "deposit cannot exceed" in (service.validation_error() or "")

    def test_a_free_service_may_still_take_a_deposit(self) -> None:
        # price 0 means "not priced here", not "free" — a deposit is still valid.
        service = Service(
            tenant_id=TENANT,
            name="Consultation",
            duration_minutes=30,
            price_cents=0,
            deposit_cents=5_000,
        )
        assert service.validation_error() is None

    def test_a_zero_or_negative_duration_is_rejected(self) -> None:
        for duration in (0, -30):
            service = Service(
                tenant_id=TENANT, name="Consultation", duration_minutes=duration
            )
            assert service.validation_error() is not None

    def test_currency_is_normalized_to_three_upper_case_letters(self) -> None:
        service = Service(
            tenant_id=TENANT, name="X", duration_minutes=30, currency=" aed "
        ).normalized()
        assert service.currency == "AED"


class TestLocationAndResource:
    def test_a_location_requires_a_real_iana_timezone(self) -> None:
        def _loc(tz: str) -> Location:
            return Location(tenant_id=TENANT, name="Dubai", timezone=tz)

        assert _loc("Asia/Dubai").validation_error() is None
        assert _loc("GMT+4").validation_error() is not None

    def test_a_utc_offset_is_not_a_timezone(self) -> None:
        # The whole reason rules are stored as wall-clock: an offset is wrong for
        # half the year anywhere observing daylight saving.
        assert not is_valid_timezone("+04:00")
        assert is_valid_timezone("Europe/London")

    def test_a_resource_needs_capacity_of_at_least_one(self) -> None:
        assert Resource(tenant_id=TENANT, name="Room 1", capacity=0).validation_error() is not None

    def test_an_unknown_resource_kind_is_rejected(self) -> None:
        assert Resource(tenant_id=TENANT, name="X", kind="spaceship").validation_error() is not None


class TestAvailabilityRuleAndBlock:
    def test_a_window_must_end_after_it_starts(self) -> None:
        rule = AvailabilityRule(
            tenant_id=TENANT,
            owner_kind="location",
            owner_id=new_id(),
            weekday=0,
            start_time=time(17, 0),
            end_time=time(9, 0),
        )
        assert "end after it starts" in (rule.validation_error() or "")

    def test_the_weekday_must_be_a_real_day(self) -> None:
        for weekday in (-1, 7):
            rule = AvailabilityRule(
                tenant_id=TENANT,
                owner_kind="location",
                owner_id=new_id(),
                weekday=weekday,
                start_time=time(9, 0),
                end_time=time(17, 0),
            )
            assert rule.validation_error() is not None

    def test_a_blocked_period_must_have_positive_length(self) -> None:
        block = BlockedPeriod(
            tenant_id=TENANT,
            owner_kind="resource",
            owner_id=new_id(),
            starts_at=START,
            ends_at=START,
        )
        assert block.validation_error() is not None


class TestSlotHold:
    def test_a_hold_expires_on_its_own_clock(self) -> None:
        hold = SlotHold(
            tenant_id=TENANT,
            service_id=ServiceId(new_id()),
            location_id=LocationId(new_id()),
            starts_at=START,
            ends_at=START + timedelta(minutes=30),
            resource_ids=[ResourceId(new_id())],
            expires_at=START + DEFAULT_HOLD_TTL,
        )
        assert not hold.is_expired(START)
        assert not hold.is_expired(START + DEFAULT_HOLD_TTL - timedelta(seconds=1))
        assert hold.is_expired(START + DEFAULT_HOLD_TTL)


class TestIdempotencyMustNotResurrectDeadAppointments:
    """A regression from live testing, and a section-61-class failure.

    Booking used the same idempotency key for the same (customer, slot), so
    rebooking a slot the customer had previously CANCELLED returned the old
    cancelled row as an "already booked" replay. The AI agent then told the
    customer their appointment was confirmed — into a row that no longer
    existed as a booking.

    The rule that fixes it lives on the entity: only an appointment that still
    occupies its slot can be a replay.
    """

    def test_a_cancelled_appointment_is_not_a_valid_replay(self) -> None:
        appointment = _appointment(status="confirmed")
        appointment.transition_to("cancelled", actor_kind="customer")
        # `occupies_slot` is the check BookAppointment now makes before treating
        # an idempotency hit as a replay.
        assert not appointment.occupies_slot

    def test_a_live_appointment_is_a_valid_replay(self) -> None:
        for status in ("pending", "confirmed", "checked_in", "completed"):
            assert _appointment(status=status).occupies_slot

    def test_a_no_show_is_not_a_valid_replay_either(self) -> None:
        # Same reasoning: the slot went back to the calendar, so a customer
        # rebooking it is making a new appointment, not retrying an old request.
        appointment = _appointment(status="confirmed")
        appointment.transition_to("no_show", actor_kind="system")
        assert not appointment.occupies_slot
