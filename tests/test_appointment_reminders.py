"""Guard: one reminder, on time, to the right people.

A reminder is a message to a real customer that cannot be unsent, so the two
things that must never happen are sending twice and sending late. Both are
decided by `Appointment.needs_reminder`, which is why it is a pure predicate on
the entity rather than a WHERE clause the sweep happens to get right.

The "late" half is the one that is easy to miss. This host sleeps and redeploys,
so a sweep genuinely does wake up long after it should have — and a reminder
about an appointment somebody is already sitting in is worse than no reminder,
because it reads as a system that does not know what time it is.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from src.application.use_cases.appointment_reminders import build_reminder
from src.domain.scheduling.entities import Appointment
from src.domain.shared.identifiers import LocationId, ServiceId, TenantId, new_id

LEAD = timedelta(minutes=30)
NOW = datetime(2026, 9, 1, 9, 0, tzinfo=UTC)


def _appointment(*, minutes_away: float, status: str = "confirmed", **kw) -> Appointment:
    starts = NOW + timedelta(minutes=minutes_away)
    return Appointment(
        tenant_id=TenantId(new_id()),
        location_id=LocationId(new_id()),
        service_id=ServiceId(new_id()),
        starts_at=starts,
        ends_at=starts + timedelta(minutes=45),
        customer_name="Ahmed Khan",
        customer_phone="+919220910108",
        status=status,  # type: ignore[arg-type]
        **kw,
    )


# --- when a reminder is due ---------------------------------------------------


def test_an_appointment_inside_the_window_is_due() -> None:
    assert _appointment(minutes_away=20).needs_reminder(now=NOW, lead=LEAD)


def test_the_far_edge_of_the_window_is_due() -> None:
    # Exactly on the lead time counts, or a sweep landing on the boundary skips
    # it and the next tick finds it already past.
    assert _appointment(minutes_away=30).needs_reminder(now=NOW, lead=LEAD)


def test_an_appointment_beyond_the_window_waits() -> None:
    assert not _appointment(minutes_away=31).needs_reminder(now=NOW, lead=LEAD)


def test_a_booking_made_inside_the_window_is_reminded_immediately() -> None:
    # Deliberate: someone who books for 10 minutes' time should still get the
    # nudge. It is also why the message states a clock time rather than
    # "in 30 minutes", which would be false for exactly this person.
    assert _appointment(minutes_away=10).needs_reminder(now=NOW, lead=LEAD)


# --- never late ---------------------------------------------------------------


def test_an_appointment_that_has_already_started_is_never_reminded() -> None:
    # The failure a late sweep causes: telling someone about a slot they are
    # already sitting in.
    assert not _appointment(minutes_away=-1).needs_reminder(now=NOW, lead=LEAD)


def test_an_appointment_starting_exactly_now_is_not_reminded() -> None:
    assert not _appointment(minutes_away=0).needs_reminder(now=NOW, lead=LEAD)


def test_a_sweep_that_woke_up_an_hour_late_sends_nothing_stale() -> None:
    # The redeploy case, end to end: the appointment was due a reminder at
    # 08:45 and the sweep did not run until 10:00.
    appointment = _appointment(minutes_away=15)
    late = NOW + timedelta(hours=1)
    assert not appointment.needs_reminder(now=late, lead=LEAD)


# --- never twice --------------------------------------------------------------


def test_an_already_reminded_appointment_is_not_reminded_again() -> None:
    appointment = _appointment(minutes_away=20)
    appointment.mark_reminded(now=NOW)
    assert not appointment.needs_reminder(now=NOW, lead=LEAD)


def test_marking_records_when_rather_than_merely_whether() -> None:
    # "Did we remind them, and when" is what the detail view and any support
    # conversation both want; a boolean throws the second half away.
    appointment = _appointment(minutes_away=20)
    appointment.mark_reminded(now=NOW)
    assert appointment.reminder_sent_at == NOW


# --- appointments that should never produce one -------------------------------


@pytest.mark.parametrize("status", ["cancelled", "no_show", "completed", "rescheduled"])
def test_a_finished_or_cancelled_appointment_is_never_reminded(status: str) -> None:
    # Reminding someone about an appointment they cancelled is the single most
    # embarrassing thing this sweep could do.
    assert not _appointment(minutes_away=20, status=status).needs_reminder(
        now=NOW, lead=LEAD
    )


@pytest.mark.parametrize("status", ["pending", "confirmed", "awaiting_confirmation"])
def test_a_live_appointment_in_any_open_status_is_reminded(status: str) -> None:
    assert _appointment(minutes_away=20, status=status).needs_reminder(now=NOW, lead=LEAD)


# --- the message --------------------------------------------------------------


def test_the_message_states_a_clock_time_not_a_countdown() -> None:
    appointment = _appointment(minutes_away=20, customer_timezone="Asia/Kolkata")
    body = build_reminder(appointment, service_name="your cleaning", location_name="Wakad")
    assert "minutes" not in body
    assert "2:50 PM" in body  # 09:20 UTC rendered in IST


def test_the_message_is_rendered_in_the_zone_the_customer_was_quoted_in() -> None:
    # The whole point of storing `customer_timezone`: a reminder in the clinic's
    # zone is the wrong time for a customer who booked from elsewhere.
    appointment = _appointment(minutes_away=20, customer_timezone="Europe/London")
    assert "10:20 AM" in build_reminder(appointment, service_name="", location_name="")


def test_an_unknown_timezone_still_produces_a_message() -> None:
    # A bad zone string on one appointment must not stop the sweep for
    # everyone else — the time falls back to UTC rather than raising.
    appointment = _appointment(minutes_away=20, customer_timezone="Mars/Olympus")
    assert "9:20 AM" in build_reminder(appointment, service_name="", location_name="")


def test_the_message_uses_the_first_name_only() -> None:
    body = build_reminder(
        _appointment(minutes_away=20), service_name="", location_name=""
    )
    assert body.startswith("Hi Ahmed,")


def test_a_nameless_booking_still_reads_naturally() -> None:
    appointment = _appointment(minutes_away=20)
    appointment.customer_name = ""
    body = build_reminder(appointment, service_name="", location_name="")
    assert body.startswith("Hi, ")
    assert "your appointment" in body
