"""The availability engine, exercised where scheduling software actually breaks.

Hermetic by construction — the engine is a pure function, so every case here is
fabricated inputs and an assertion, with no database and no clock dependency
(`now` is always passed in). That is the point of keeping it pure: these are the
cases you cannot practically reach through an API test.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, time, timedelta
from zoneinfo import ZoneInfo

from src.domain.scheduling.availability import (
    AvailabilityInputs,
    AvailabilityRequest,
    Interval,
    compute_slots,
    reservation_window,
)
from src.domain.scheduling.entities import (
    AvailabilityRule,
    BlockedPeriod,
    Resource,
    Service,
)
from src.domain.shared.identifiers import (
    LocationId,
    ResourceId,
    ServiceId,
    TenantId,
    new_id,
)

TENANT = TenantId(new_id())
LOCATION = LocationId(new_id())


def _service(**overrides: object) -> Service:
    defaults: dict[str, object] = {
        "tenant_id": TENANT,
        "name": "Consultation",
        "duration_minutes": 30,
        "min_notice_minutes": 0,
        "max_horizon_days": 60,
    }
    defaults.update(overrides)
    return Service(**defaults)  # type: ignore[arg-type]


def _resource(name: str = "Dr Khan", **overrides: object) -> Resource:
    defaults: dict[str, object] = {"tenant_id": TENANT, "name": name}
    defaults.update(overrides)
    return Resource(**defaults)  # type: ignore[arg-type]


def _rule(
    owner_id: uuid.UUID,
    weekday: int,
    start: str = "09:00",
    end: str = "17:00",
    owner_kind: str = "location",
) -> AvailabilityRule:
    return AvailabilityRule(
        tenant_id=TENANT,
        owner_kind=owner_kind,  # type: ignore[arg-type]
        owner_id=owner_id,
        weekday=weekday,
        start_time=time.fromisoformat(start),
        end_time=time.fromisoformat(end),
    )


def _inputs(
    service: Service,
    resources: dict[str, list[Resource]],
    rules: dict[object, list[AvailabilityRule]],
    blocks: dict[object, list[BlockedPeriod]] | None = None,
    busy: dict[ResourceId, list[Interval]] | None = None,
) -> AvailabilityInputs:
    return AvailabilityInputs(
        service=service,
        candidates_by_role=resources,
        rules_by_owner=rules,
        blocks_by_owner=blocks or {},
        busy_by_resource=busy or {},
    )


def _request(
    start: datetime, end: datetime, tz: str = "UTC", **overrides: object
) -> AvailabilityRequest:
    defaults: dict[str, object] = {
        "tenant_id": TENANT,
        "location_id": LOCATION,
        "service_id": ServiceId(new_id()),
        "range_start": start,
        "range_end": end,
        "location_timezone": tz,
    }
    defaults.update(overrides)
    return AvailabilityRequest(**defaults)  # type: ignore[arg-type]


# 2026-03-02 is a Monday. Fixed rather than relative to today so the weekday
# rules under test mean the same thing on every run.
MONDAY = datetime(2026, 3, 2, 0, 0, tzinfo=UTC)


class TestTheBasicGrid:
    def test_a_day_of_opening_hours_becomes_evenly_spaced_slots(self) -> None:
        doctor = _resource()
        service = _service(duration_minutes=30)
        inputs = _inputs(
            service,
            {"primary": [doctor]},
            {LOCATION: [_rule(LOCATION, 0, "09:00", "12:00")]},
        )
        slots = compute_slots(
            _request(MONDAY, MONDAY + timedelta(days=1)), inputs, now=MONDAY
        )

        assert slots, "an open Monday must produce slots"
        assert slots[0].starts_at == datetime(2026, 3, 2, 9, 0, tzinfo=UTC)
        # 09:00-12:00 at 15-minute granularity, last 30-minute slot at 11:30.
        assert slots[-1].starts_at == datetime(2026, 3, 2, 11, 30, tzinfo=UTC)
        gaps = {
            (b.starts_at - a.starts_at).total_seconds() / 60
            for a, b in zip(slots, slots[1:], strict=False)
        }
        assert gaps == {15}

    def test_a_slot_carries_the_resources_that_would_serve_it(self) -> None:
        doctor = _resource()
        inputs = _inputs(
            _service(), {"primary": [doctor]}, {LOCATION: [_rule(LOCATION, 0)]}
        )
        slots = compute_slots(
            _request(MONDAY, MONDAY + timedelta(days=1)), inputs, now=MONDAY
        )
        # Not advisory: the booking call reserves exactly these.
        assert slots[0].resource_ids == (doctor.id,)

    def test_a_branch_with_no_hours_is_closed_rather_than_always_open(self) -> None:
        # The failure this guards: treating "no rules" as 24/7, which books
        # customers at 3am.
        inputs = _inputs(_service(), {"primary": [_resource()]}, {})
        assert (
            compute_slots(
                _request(MONDAY, MONDAY + timedelta(days=1)), inputs, now=MONDAY
            )
            == []
        )

    def test_a_service_with_no_eligible_resource_is_unbookable(self) -> None:
        # A consultation with no room is not a consultation.
        inputs = _inputs(_service(), {"room": []}, {LOCATION: [_rule(LOCATION, 0)]})
        assert (
            compute_slots(
                _request(MONDAY, MONDAY + timedelta(days=1)), inputs, now=MONDAY
            )
            == []
        )

    def test_rules_for_other_weekdays_do_not_open_this_one(self) -> None:
        inputs = _inputs(
            _service(),
            {"primary": [_resource()]},
            {LOCATION: [_rule(LOCATION, 2)]},  # Wednesday only
        )
        assert (
            compute_slots(
                _request(MONDAY, MONDAY + timedelta(hours=23)), inputs, now=MONDAY
            )
            == []
        )


class TestBuffers:
    def test_a_buffer_shortens_the_bookable_day_without_lengthening_the_appointment(
        self,
    ) -> None:
        service = _service(
            duration_minutes=30, buffer_before_minutes=5, buffer_after_minutes=10
        )
        inputs = _inputs(
            service,
            {"primary": [_resource()]},
            {LOCATION: [_rule(LOCATION, 0, "09:00", "10:00")]},
        )
        slots = compute_slots(
            _request(MONDAY, MONDAY + timedelta(days=1)), inputs, now=MONDAY
        )

        # The customer is still shown a 30-minute appointment...
        assert all(
            (s.ends_at - s.starts_at) == timedelta(minutes=30) for s in slots
        )
        # ...but 09:00 cannot be offered: its 5-minute lead-in starts at 08:55,
        # before the branch opens.
        assert slots[0].starts_at == datetime(2026, 3, 2, 9, 15, tzinfo=UTC)
        # And the last slot must leave room for its 10-minute cleanup by 10:00.
        assert slots[-1].ends_at + timedelta(minutes=10) <= datetime(
            2026, 3, 2, 10, 0, tzinfo=UTC
        )

    def test_the_reservation_window_is_what_the_buffers_say(self) -> None:
        # Availability and booking must compute this identically, or a slot the
        # engine offered gets rejected on save.
        service = _service(
            duration_minutes=30, buffer_before_minutes=5, buffer_after_minutes=10
        )
        window = reservation_window(service, datetime(2026, 3, 2, 9, 30, tzinfo=UTC))
        assert window.start == datetime(2026, 3, 2, 9, 25, tzinfo=UTC)
        assert window.end == datetime(2026, 3, 2, 10, 10, tzinfo=UTC)

    def test_a_booking_blocks_the_neighbouring_slot_through_its_buffer(self) -> None:
        doctor = _resource()
        service = _service(duration_minutes=30, buffer_after_minutes=30)
        # An appointment 09:00-09:30 reserves through 10:00 with its cleanup.
        busy = {
            doctor.id: [
                Interval(
                    datetime(2026, 3, 2, 9, 0, tzinfo=UTC),
                    datetime(2026, 3, 2, 10, 0, tzinfo=UTC),
                )
            ]
        }
        inputs = _inputs(
            service,
            {"primary": [doctor]},
            {LOCATION: [_rule(LOCATION, 0, "09:00", "12:00")]},
            busy=busy,
        )
        slots = compute_slots(
            _request(MONDAY, MONDAY + timedelta(days=1)), inputs, now=MONDAY
        )
        assert slots[0].starts_at == datetime(2026, 3, 2, 10, 0, tzinfo=UTC)


class TestExistingBookingsAndBlocks:
    def test_a_busy_interval_removes_exactly_the_slots_it_covers(self) -> None:
        doctor = _resource()
        busy = {
            doctor.id: [
                Interval(
                    datetime(2026, 3, 2, 10, 0, tzinfo=UTC),
                    datetime(2026, 3, 2, 11, 0, tzinfo=UTC),
                )
            ]
        }
        inputs = _inputs(
            _service(),
            {"primary": [doctor]},
            {LOCATION: [_rule(LOCATION, 0, "09:00", "12:00")]},
            busy=busy,
        )
        starts = {
            s.starts_at
            for s in compute_slots(
                _request(MONDAY, MONDAY + timedelta(days=1)), inputs, now=MONDAY
            )
        }
        assert datetime(2026, 3, 2, 9, 30, tzinfo=UTC) in starts
        assert datetime(2026, 3, 2, 10, 0, tzinfo=UTC) not in starts
        assert datetime(2026, 3, 2, 10, 30, tzinfo=UTC) not in starts
        # Half-open intervals: an appointment ending at 11:00 does not block one
        # starting at 11:00.
        assert datetime(2026, 3, 2, 11, 0, tzinfo=UTC) in starts

    def test_leave_on_one_resource_falls_through_to_another(self) -> None:
        on_leave, cover = _resource("Dr Khan"), _resource("Dr Ada")
        blocks = {
            on_leave.id: [
                BlockedPeriod(
                    tenant_id=TENANT,
                    owner_kind="resource",
                    owner_id=on_leave.id,
                    starts_at=datetime(2026, 3, 2, 0, 0, tzinfo=UTC),
                    ends_at=datetime(2026, 3, 3, 0, 0, tzinfo=UTC),
                    reason="Annual leave",
                )
            ]
        }
        inputs = _inputs(
            _service(),
            {"primary": [on_leave, cover]},
            {LOCATION: [_rule(LOCATION, 0)]},
            blocks=blocks,
        )
        slots = compute_slots(
            _request(MONDAY, MONDAY + timedelta(days=1)), inputs, now=MONDAY
        )
        assert slots, "the covering doctor keeps the day bookable"
        assert {r for s in slots for r in s.resource_ids} == {cover.id}

    def test_a_branch_holiday_closes_the_day_for_everyone(self) -> None:
        doctor = _resource()
        blocks = {
            LOCATION: [
                BlockedPeriod(
                    tenant_id=TENANT,
                    owner_kind="location",
                    owner_id=LOCATION,
                    starts_at=datetime(2026, 3, 2, 0, 0, tzinfo=UTC),
                    ends_at=datetime(2026, 3, 3, 0, 0, tzinfo=UTC),
                    reason="Public holiday",
                )
            ]
        }
        inputs = _inputs(
            _service(),
            {"primary": [doctor]},
            {LOCATION: [_rule(LOCATION, 0)]},
            blocks=blocks,
        )
        assert (
            compute_slots(
                _request(MONDAY, MONDAY + timedelta(days=1)), inputs, now=MONDAY
            )
            == []
        )

    def test_an_inactive_resource_is_not_offered(self) -> None:
        inputs = _inputs(
            _service(),
            {"primary": [_resource(is_active=False)]},
            {LOCATION: [_rule(LOCATION, 0)]},
        )
        assert (
            compute_slots(
                _request(MONDAY, MONDAY + timedelta(days=1)), inputs, now=MONDAY
            )
            == []
        )

    def test_an_inactive_service_is_not_offered(self) -> None:
        inputs = _inputs(
            _service(is_active=False),
            {"primary": [_resource()]},
            {LOCATION: [_rule(LOCATION, 0)]},
        )
        assert (
            compute_slots(
                _request(MONDAY, MONDAY + timedelta(days=1)), inputs, now=MONDAY
            )
            == []
        )


class TestMultipleRequiredResources:
    """Section 10: a slot exists only when EVERY required role can be filled."""

    def test_a_slot_needs_both_a_practitioner_and_a_room(self) -> None:
        doctor, room = _resource("Dr Khan"), _resource("Room 1", kind="room")
        inputs = _inputs(
            _service(),
            {"practitioner": [doctor], "room": [room]},
            {LOCATION: [_rule(LOCATION, 0, "09:00", "10:00")]},
        )
        slots = compute_slots(
            _request(MONDAY, MONDAY + timedelta(days=1)), inputs, now=MONDAY
        )
        assert slots
        assert set(slots[0].resource_ids) == {doctor.id, room.id}

    def test_a_busy_room_removes_the_slot_even_when_the_doctor_is_free(self) -> None:
        doctor, room = _resource("Dr Khan"), _resource("Room 1", kind="room")
        busy = {
            room.id: [
                Interval(
                    datetime(2026, 3, 2, 9, 0, tzinfo=UTC),
                    datetime(2026, 3, 2, 10, 0, tzinfo=UTC),
                )
            ]
        }
        inputs = _inputs(
            _service(),
            {"practitioner": [doctor], "room": [room]},
            {LOCATION: [_rule(LOCATION, 0, "09:00", "10:00")]},
            busy=busy,
        )
        assert (
            compute_slots(
                _request(MONDAY, MONDAY + timedelta(days=1)), inputs, now=MONDAY
            )
            == []
        )

    def test_one_resource_is_never_assigned_to_two_roles_at_once(self) -> None:
        # A misconfiguration (the same person eligible for both roles) must not
        # produce a slot that double-books them against themselves.
        both = _resource("Multi-role")
        inputs = _inputs(
            _service(),
            {"practitioner": [both], "assistant": [both]},
            {LOCATION: [_rule(LOCATION, 0, "09:00", "10:00")]},
        )
        assert (
            compute_slots(
                _request(MONDAY, MONDAY + timedelta(days=1)), inputs, now=MONDAY
            )
            == []
        )


class TestNoticeAndHorizon:
    def test_minimum_notice_hides_slots_that_are_too_soon(self) -> None:
        doctor = _resource()
        service = _service(min_notice_minutes=120)
        now = datetime(2026, 3, 2, 9, 0, tzinfo=UTC)
        inputs = _inputs(
            service,
            {"primary": [doctor]},
            {LOCATION: [_rule(LOCATION, 0, "09:00", "17:00")]},
        )
        slots = compute_slots(
            _request(MONDAY, MONDAY + timedelta(days=1)), inputs, now=now
        )
        assert slots[0].starts_at >= now + timedelta(minutes=120)

    def test_the_booking_horizon_bounds_how_far_ahead_slots_go(self) -> None:
        inputs = _inputs(
            _service(max_horizon_days=7),
            {"primary": [_resource()]},
            {LOCATION: [_rule(LOCATION, 0)]},
        )
        slots = compute_slots(
            _request(MONDAY, MONDAY + timedelta(days=60)), inputs, now=MONDAY
        )
        assert slots
        assert max(s.starts_at for s in slots) < MONDAY + timedelta(days=8)

    def test_a_window_entirely_in_the_past_yields_nothing(self) -> None:
        inputs = _inputs(
            _service(), {"primary": [_resource()]}, {LOCATION: [_rule(LOCATION, 0)]}
        )
        slots = compute_slots(
            _request(MONDAY, MONDAY + timedelta(days=1)),
            inputs,
            now=MONDAY + timedelta(days=30),
        )
        assert slots == []

    def test_the_result_is_capped_by_the_requested_limit(self) -> None:
        inputs = _inputs(
            _service(), {"primary": [_resource()]}, {LOCATION: [_rule(LOCATION, 0)]}
        )
        slots = compute_slots(
            _request(MONDAY, MONDAY + timedelta(days=1), limit=5), inputs, now=MONDAY
        )
        assert len(slots) == 5


class TestTimezonesAndDaylightSaving:
    """Section 52. This is the class that justifies storing rules as wall-clock."""

    def test_opening_hours_mean_local_time_not_utc(self) -> None:
        # A Dubai branch open 09:00 local is open at 05:00 UTC (UTC+4).
        doctor = _resource()
        inputs = _inputs(
            _service(),
            {"primary": [doctor]},
            {LOCATION: [_rule(LOCATION, 0, "09:00", "17:00")]},
        )
        slots = compute_slots(
            _request(MONDAY, MONDAY + timedelta(days=1), tz="Asia/Dubai"),
            inputs,
            now=MONDAY,
        )
        assert slots[0].starts_at == datetime(2026, 3, 2, 5, 0, tzinfo=UTC)

    def test_a_nine_am_rule_stays_nine_am_local_across_spring_forward(self) -> None:
        # London springs forward on 2026-03-29 (a Sunday). The Monday before is
        # GMT (09:00 local = 09:00 UTC); the Monday after is BST (09:00 local =
        # 08:00 UTC). A stored UTC offset would silently move the branch's
        # opening time by an hour; a wall-clock rule does not.
        london = ZoneInfo("Europe/London")
        doctor = _resource()
        inputs = _inputs(
            _service(),
            {"primary": [doctor]},
            {LOCATION: [_rule(LOCATION, 0, "09:00", "10:00")]},
        )

        before = datetime(2026, 3, 23, 0, 0, tzinfo=UTC)
        after = datetime(2026, 3, 30, 0, 0, tzinfo=UTC)

        first = compute_slots(
            _request(before, before + timedelta(days=1), tz="Europe/London"),
            inputs,
            now=before,
        )[0]
        second = compute_slots(
            _request(after, after + timedelta(days=1), tz="Europe/London"),
            inputs,
            now=after,
        )[0]

        # The UTC instants genuinely differ...
        assert first.starts_at == datetime(2026, 3, 23, 9, 0, tzinfo=UTC)
        assert second.starts_at == datetime(2026, 3, 30, 8, 0, tzinfo=UTC)
        # ...because both are 09:00 to someone standing in London.
        assert first.starts_at.astimezone(london).hour == 9
        assert second.starts_at.astimezone(london).hour == 9

    def test_a_fall_back_day_offers_no_duplicate_start_times(self) -> None:
        # London falls back on 2026-10-25 (a Sunday): 01:00-02:00 local happens
        # twice. A day spanning it must still produce strictly increasing,
        # unique starts rather than two 01:30 slots.
        doctor = _resource()
        inputs = _inputs(
            _service(duration_minutes=30),
            {"primary": [doctor]},
            {LOCATION: [_rule(LOCATION, 6, "00:00", "06:00")]},  # Sunday
        )
        sunday = datetime(2026, 10, 25, 0, 0, tzinfo=UTC)
        slots = compute_slots(
            _request(
                sunday - timedelta(hours=2),
                sunday + timedelta(days=1),
                tz="Europe/London",
            ),
            inputs,
            now=sunday - timedelta(days=1),
        )
        starts = [s.starts_at for s in slots]
        assert len(starts) == len(set(starts)), "no instant may be offered twice"
        assert starts == sorted(starts)

    def test_a_resource_in_another_timezone_is_intersected_correctly(self) -> None:
        # A remote consultant working 09:00-17:00 London for a Dubai branch open
        # 09:00-17:00 local overlaps 13:00-17:00 Dubai (09:00-13:00 UTC).
        consultant = _resource("Remote", timezone="Europe/London")
        inputs = _inputs(
            _service(duration_minutes=60),
            {"primary": [consultant]},
            {
                LOCATION: [_rule(LOCATION, 0, "09:00", "17:00")],
                consultant.id: [
                    _rule(consultant.id, 0, "09:00", "17:00", owner_kind="resource")
                ],
            },
        )
        slots = compute_slots(
            _request(MONDAY, MONDAY + timedelta(days=1), tz="Asia/Dubai"),
            inputs,
            now=MONDAY,
        )
        assert slots
        assert slots[0].starts_at == datetime(2026, 3, 2, 9, 0, tzinfo=UTC)
        assert max(s.ends_at for s in slots) <= datetime(2026, 3, 2, 13, 0, tzinfo=UTC)


class TestPreferredResource:
    def test_naming_a_resource_restricts_the_slots_to_that_person(self) -> None:
        khan, ada = _resource("Dr Khan"), _resource("Dr Ada")
        busy = {
            khan.id: [
                Interval(
                    datetime(2026, 3, 2, 9, 0, tzinfo=UTC),
                    datetime(2026, 3, 2, 12, 0, tzinfo=UTC),
                )
            ]
        }
        inputs = _inputs(
            _service(),
            {"primary": [khan, ada]},
            {LOCATION: [_rule(LOCATION, 0, "09:00", "12:00")]},
            busy=busy,
        )
        # Without a preference, Ada covers the morning.
        assert compute_slots(
            _request(MONDAY, MONDAY + timedelta(days=1)), inputs, now=MONDAY
        )
        # Asking for Khan specifically returns nothing rather than quietly
        # booking someone else — the customer asked for a person.
        assert (
            compute_slots(
                _request(
                    MONDAY, MONDAY + timedelta(days=1), preferred_resource_id=khan.id
                ),
                inputs,
                now=MONDAY,
            )
            == []
        )
