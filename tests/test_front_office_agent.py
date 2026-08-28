"""The AI receptionist's booking tools, and the rules that keep them honest.

Every test here is a regression from a real failure seen while driving the agent
against a live LLM. They are written against the pure helpers and the tool
contracts rather than the model, because the model is not the thing that can be
pinned — the arithmetic and the guardrail wording are.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import pytest
from src.application.agent.tools import ToolContext
from src.domain.shared.identifiers import TenantId, new_id
from src.infrastructure.agent.front_office import (
    FRONT_OFFICE_REFUSAL,
    FRONT_OFFICE_SYSTEM,
)
from src.infrastructure.agent.scheduling_tools import (
    LIVE_STATUSES,
    TIME_OF_DAY_HOURS,
    _local_day_window,
    _reference,
    _source_for,
    build_scheduling_tools,
)

TENANT = TenantId(new_id())
NOW = datetime(2026, 8, 28, 6, 0, tzinfo=UTC)


class TestTheBranchLocalDayWindow:
    """The fix for the bug that made the agent report a clinic closed on a day
    it was open.

    The agent used to be handed a UTC range to fill in, which asked it to do
    timezone arithmetic it cannot do — it does not know the branch's offset. Now
    it names a local date and a part of the day, and this converts.
    """

    def test_morning_in_dubai_is_the_right_utc_window(self) -> None:
        window = _local_day_window("2026-08-31", "morning", "Asia/Dubai", NOW)
        assert window is not None
        start, end = window
        # 06:00-12:00 local at UTC+4.
        assert start == datetime(2026, 8, 31, 2, 0, tzinfo=UTC)
        assert end == datetime(2026, 8, 31, 8, 0, tzinfo=UTC)

    def test_the_same_local_hours_differ_by_zone(self) -> None:
        # The whole point: "morning" is not a fixed UTC range.
        dubai = _local_day_window("2026-08-31", "morning", "Asia/Dubai", NOW)
        london = _local_day_window("2026-08-31", "morning", "Europe/London", NOW)
        assert dubai is not None and london is not None
        assert dubai[0] != london[0]

    def test_evening_reads_as_evening_locally(self) -> None:
        window = _local_day_window("2026-08-31", "evening", "Asia/Dubai", NOW)
        assert window is not None
        local_start = window[0].astimezone(ZoneInfo("Asia/Dubai"))
        assert local_start.hour == 17

    def test_a_day_with_no_preference_covers_the_whole_day(self) -> None:
        window = _local_day_window("2026-08-31", "any", "Asia/Dubai", NOW)
        assert window is not None
        assert (window[1] - window[0]).total_seconds() > 20 * 3600

    def test_an_unknown_preference_falls_back_to_the_whole_day(self) -> None:
        # A model that invents "lunchtime" must not get an empty window.
        window = _local_day_window("2026-08-31", "lunchtime", "Asia/Dubai", NOW)
        assert window is not None
        assert (window[1] - window[0]).total_seconds() > 20 * 3600

    def test_a_window_never_starts_in_the_past(self) -> None:
        # Asking for this morning at midday must not offer 6am.
        window = _local_day_window("2026-08-28", "morning", "Asia/Dubai", NOW)
        assert window is not None
        assert window[0] >= NOW

    def test_an_unparseable_date_is_rejected_rather_than_guessed(self) -> None:
        for bad in ("next tuesday", "31/08/2026", "", "tomorrow"):
            assert _local_day_window(bad, "morning", "Asia/Dubai", NOW) is None

    def test_an_unknown_timezone_degrades_to_utc_instead_of_raising(self) -> None:
        # A bad zone must not take down an availability search.
        window = _local_day_window("2026-08-31", "morning", "Mars/Olympus", NOW)
        assert window is not None

    def test_daylight_saving_is_handled_by_the_zone_not_by_arithmetic(self) -> None:
        # London: 09:00 local is 09:00Z in winter and 08:00Z in summer.
        summer = _local_day_window("2026-08-31", "morning", "Europe/London", NOW)
        winter = _local_day_window("2026-12-14", "morning", "Europe/London", NOW)
        assert summer is not None and winter is not None
        assert summer[0].astimezone(ZoneInfo("Europe/London")).hour == 6
        assert winter[0].astimezone(ZoneInfo("Europe/London")).hour == 6
        # Same local hour, different UTC hour — which is the point.
        assert summer[0].hour != winter[0].hour

    def test_the_parts_of_the_day_do_not_overlap(self) -> None:
        morning, afternoon, evening = (
            TIME_OF_DAY_HOURS["morning"],
            TIME_OF_DAY_HOURS["afternoon"],
            TIME_OF_DAY_HOURS["evening"],
        )
        assert morning[1] <= afternoon[0]
        assert afternoon[1] <= evening[0]


class TestCustomerFacingReferences:
    def test_a_reference_is_short_enough_to_read_aloud(self) -> None:
        reference = _reference(uuid.uuid4())
        assert reference.startswith("APT-")
        assert len(reference) == 12

    def test_a_reference_is_derived_so_it_cannot_drift_from_the_id(self) -> None:
        appointment_id = uuid.uuid4()
        assert _reference(appointment_id) == _reference(appointment_id)
        assert appointment_id.hex[:8].upper() in _reference(appointment_id)

    def test_different_appointments_get_different_references(self) -> None:
        assert _reference(uuid.uuid4()) != _reference(uuid.uuid4())


class TestChannelAttribution:
    """Spec section 44 — a wrong source silently corrupts the report that says
    which channel produces business."""

    def test_a_known_channel_is_recorded(self) -> None:
        for source in ("whatsapp", "ai_voice", "web_widget"):
            ctx = ToolContext(tenant_id=TENANT, extras={"source": source})
            assert _source_for(ctx) == source

    def test_an_unknown_channel_falls_back_rather_than_being_stored(self) -> None:
        ctx = ToolContext(tenant_id=TENANT, extras={"source": "carrier_pigeon"})
        assert _source_for(ctx) == "api"

    def test_a_missing_channel_falls_back(self) -> None:
        assert _source_for(ToolContext(tenant_id=TENANT)) == "api"


class TestLookupScope:
    def test_a_cancelled_appointment_is_not_something_to_reschedule(self) -> None:
        # Lookup drives reschedule and cancel, so a cancelled appointment
        # appearing there would let the agent try to move a dead booking.
        assert "cancelled" not in LIVE_STATUSES
        assert "no_show" not in LIVE_STATUSES
        assert "completed" not in LIVE_STATUSES
        assert "confirmed" in LIVE_STATUSES


class TestTheGuardrailsAreWrittenDown:
    """Section 61 is enforced structurally, but the wording is what steers the
    model away from the failure in the first place — so it is pinned."""

    @pytest.fixture
    def tools(self):  # type: ignore[no-untyped-def]
        return {t.spec.name: t.spec for t in build_scheduling_tools(lambda: None)}

    def test_every_mutating_tool_forbids_claiming_success_early(self, tools) -> None:  # type: ignore[no-untyped-def]
        for name in ("book_appointment", "cancel_appointment", "reschedule_appointment"):
            assert "Never" in tools[name].description
            assert "unless this" in tools[name].description

    def test_the_availability_tool_forbids_inventing_a_time(self, tools) -> None:  # type: ignore[no-untyped-def]
        assert "never guess or invent" in tools["find_available_slots"].description

    def test_the_availability_tool_asks_for_a_local_date_not_a_utc_range(
        self, tools
    ) -> None:  # type: ignore[no-untyped-def]
        # The regression: a UTC range asked the model to convert time zones.
        description = tools["find_available_slots"].description
        assert "YYYY-MM-DD" in description
        assert "do not convert anything yourself" in description
        assert "date" in tools["find_available_slots"].parameters
        assert "from_date" not in tools["find_available_slots"].parameters

    def test_holding_is_marked_as_new_bookings_only(self, tools) -> None:  # type: ignore[no-untyped-def]
        # The regression: reschedules were detouring through the booking flow,
        # holding a slot and re-collecting details the appointment already had.
        assert "never when moving" in tools["create_slot_hold"].description.lower()

    def test_reschedule_says_it_needs_nothing_else(self, tools) -> None:  # type: ignore[no-untyped-def]
        description = tools["reschedule_appointment"].description
        assert "ONLY call a reschedule needs" in description
        assert "do NOT hold" in description


class TestTheSystemPrompt:
    def test_it_carries_today_so_the_model_can_resolve_tomorrow(self) -> None:
        # A model has no clock. Without this, "Monday" is unresolvable and the
        # failure looks like no availability rather than like an error.
        assert "{today}" in FRONT_OFFICE_SYSTEM

    def test_it_renders_with_the_values_the_loop_supplies(self) -> None:
        rendered = FRONT_OFFICE_SYSTEM.format(
            catalog="- a_tool()", refusal=FRONT_OFFICE_REFUSAL, today="Friday 28 August 2026"
        )
        assert "Friday 28 August 2026" in rendered
        assert FRONT_OFFICE_REFUSAL in rendered
        # The JSON action shape must survive .format() un-mangled, or the loop
        # cannot parse a single reply.
        assert '{"thought"' in rendered

    def test_it_states_both_section_61_rules(self) -> None:
        assert "NEVER state or suggest an appointment time" in FRONT_OFFICE_SYSTEM
        assert "NEVER tell a customer something is booked" in FRONT_OFFICE_SYSTEM

    def test_it_warns_that_a_hold_is_not_a_booking(self) -> None:
        # The regression: the agent held a slot, replied, and left the customer
        # believing they were booked when the hold was about to expire.
        assert "A held slot is NOT a booking" in FRONT_OFFICE_SYSTEM

    def test_the_refusal_offers_a_human_rather_than_dead_ending(self) -> None:
        assert "colleague" in FRONT_OFFICE_REFUSAL
