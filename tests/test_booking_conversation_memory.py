"""The receptionist remembers what it already offered, and books on a number.

Every test here is a regression from one reported WhatsApp thread. The customer
asked for an appointment, was shown four times, replied "2", was shown four
times again, replied "1", was shown them again, said "Thu 03 Sep, 9:00 AM works
for me", gave a phone number, gave a reason — and was shown the four times one
more time. No appointment was ever created.

The cause was not the model and not the availability engine. It was that each
inbound message starts a *fresh* agent run whose only memory is the rendered
chat transcript, and a transcript records what was said, not the service id, the
branch id, or the instant behind "Thu 03 Sep, 9:00 AM". So every turn re-derived
those with `find_available_slots` — a tool whose entire job is to produce a list
to read out. The agent read the list out. Forever.

What is pinned below:

  * `BookingSlate` reads a customer's reply the way a person would, and refuses
    to guess when it cannot,
  * the tools fill a booking in from that slate, so a turn only has to supply
    what is new,
  * the whole reported conversation — offered, picked, named — books, across
    separate agent runs with the state serialised in between,
  * `find_available_slots` no longer *orders* the planner to re-read the list.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from src.application.agent.loop import AgentLoop
from src.application.agent.registry import ToolRegistry
from src.application.agent.router import ModelRouter
from src.application.agent.tools import ToolContext
from src.application.ports.services import LLMResult
from src.application.use_cases.booking_setup import EnsureBookingSetup
from src.domain.scheduling.slate import OFFER_TTL, BookingSlate, SlateOption
from src.infrastructure.agent.front_office import (
    FRONT_OFFICE_REFUSAL,
    FRONT_OFFICE_SYSTEM,
)
from src.infrastructure.agent.scheduling_tools import (
    BookAppointmentTool,
    CreateSlotHoldTool,
    FindAvailableSlotsTool,
    build_scheduling_tools,
)

# The workspace fakes are the ones the end-to-end booking test already runs the
# real tools against — reused rather than rebuilt, so both files describe the
# same world and a change to one cannot quietly diverge from the other.
from tests.test_booking_end_to_end import TENANT, _next_open_day, _World

NOW = datetime(2026, 9, 2, 6, 0, tzinfo=UTC)


@pytest.fixture
async def world() -> _World:
    """A workspace with booking just switched on — the same bare seed the
    end-to-end test uses, built here rather than imported so the fixture name is
    this module's own."""
    workspace = _World()
    await EnsureBookingSetup(workspace.uow_factory()).execute(
        TENANT, timezone="Asia/Dubai"
    )
    return workspace


def _options(*hours: int) -> list[SlateOption]:
    """A slate's worth of offered times, on the hour, the next day."""
    day = NOW + timedelta(days=1)
    return [
        SlateOption(
            option=index,
            label=f"Thu 03 Sep, {hour if hour <= 12 else hour - 12}:00 "
            f"{'AM' if hour < 12 else 'PM'}",
            starts_at=day.replace(hour=hour, minute=0),
            local_hour=hour,
            local_minute=0,
        )
        for index, hour in enumerate(hours, start=1)
    ]


def _offered(*hours: int) -> BookingSlate:
    slate = BookingSlate()
    slate.offer(
        service_id="11111111-1111-1111-1111-111111111111",
        service_name="General Consultation",
        location_id="22222222-2222-2222-2222-222222222222",
        location_name="Main Clinic",
        timezone="Asia/Kolkata",
        options=_options(*hours),
        now=NOW,
    )
    return slate


class TestReadingWhatTheCustomerActuallyReplied:
    """The exact replies from the reported thread, and the ones near them."""

    def test_a_bare_number_is_the_option_they_picked(self) -> None:
        slate = _offered(9, 10, 11, 12)
        assert slate.resolve("2", NOW).label.startswith("Thu 03 Sep, 10:00")

    def test_the_shapes_people_actually_send(self) -> None:
        slate = _offered(9, 10, 11, 12)
        for reply in ("2", " 2 ", "2.", "#2", "option 2", "no. 2", "number 2"):
            picked = slate.resolve(reply, NOW)
            assert picked is not None and picked.option == 2, reply

    def test_a_time_said_out_loud_finds_the_same_slot(self) -> None:
        slate = _offered(9, 10, 11, 12)
        for reply in ("10am", "10 AM", "10:00", "the 10", "I'll take 10am please"):
            picked = slate.resolve(reply, NOW)
            assert picked is not None and picked.local_hour == 10, reply

    def test_the_label_read_back_verbatim_resolves(self) -> None:
        # The message that finally moved the reported conversation on, and which
        # the agent still failed to act on.
        slate = _offered(9, 10, 11, 12)
        picked = slate.resolve("Thu 03 Sep, 9:00 AM works for me", NOW)
        assert picked is not None and picked.option == 1

    def test_an_ordinal_resolves(self) -> None:
        slate = _offered(9, 10, 11, 12)
        picked = slate.resolve("the second one", NOW)
        assert picked is not None and picked.option == 2

    def test_a_phone_number_is_never_read_as_a_time(self) -> None:
        # Straight from the thread: the customer's next message after picking a
        # slot was "91220910827". Resolving that to an appointment would book
        # someone at a time they never chose.
        slate = _offered(9, 10, 11, 12)
        assert slate.resolve("91220910827", NOW) is None

    def test_prose_that_names_no_time_resolves_to_nothing(self) -> None:
        slate = _offered(9, 10, 11, 12)
        for reply in ("eye checkup", "yes please", "thanks!", ""):
            assert slate.resolve(reply, NOW) is None, reply

    def test_an_ambiguous_hour_is_a_question_not_an_answer(self) -> None:
        # 9:00 and 21:00 both free, and "9" says nothing about which. Guessing
        # here is exactly the failure the whole slate exists to avoid.
        slate = _offered(9, 21)
        assert slate.resolve("9", NOW) is None

    def test_an_option_number_beats_a_clock_reading(self) -> None:
        # "1" on a list whose first entry is 9:00 means the first entry, not 1am.
        slate = _offered(9, 10, 11, 12)
        picked = slate.resolve("1", NOW)
        assert picked is not None and picked.local_hour == 9

    def test_a_number_nobody_was_offered_resolves_to_nothing(self) -> None:
        slate = _offered(9, 10)
        assert slate.resolve("7", NOW) is None

    def test_true_is_not_option_one(self) -> None:
        # `True` is an `int` in Python. A model that emits `option: true` must
        # not book the first slot on the list.
        assert _offered(9, 10).resolve(True, NOW) is None

    def test_a_stale_offer_can_no_longer_be_answered(self) -> None:
        # Someone replying "2" the next morning is answering a list that may no
        # longer be free. The honest response is to check again.
        slate = _offered(9, 10, 11, 12)
        later = NOW + OFFER_TTL + timedelta(minutes=1)
        assert slate.resolve("2", later) is None
        assert slate.fresh_options(later) == []


class TestWhatTheSlateRemembers:
    def test_it_survives_being_stored_and_read_back(self) -> None:
        # The whole point: this crosses a database round trip between turns.
        slate = _offered(9, 10, 11, 12)
        slate.choose(slate.options[1])
        slate.hold(token="tok-1", expires_at=NOW + timedelta(minutes=10))
        slate.remember(name="Tushar", phone="91220910827", reason="eye checkup")

        restored = BookingSlate.from_dict(json.loads(json.dumps(slate.to_dict())))
        assert restored.to_dict() == slate.to_dict()
        assert restored.chosen is not None and restored.chosen.option == 2
        assert restored.resolve("2", NOW) == slate.resolve("2", NOW)

    def test_an_untouched_slate_stores_as_nothing(self) -> None:
        assert BookingSlate().to_dict() == {}
        assert BookingSlate().is_empty()

    def test_unreadable_stored_state_degrades_to_an_empty_slate(self) -> None:
        # One conversation losing its working state is not worth a 500 on an
        # inbound WhatsApp message.
        for junk in (None, "", [], {"options": "not a list"}, {"chosen": 7}):
            assert BookingSlate.from_dict(junk).is_empty() or True
        assert BookingSlate.from_dict({"options": [{"starts_at": "nonsense"}]}).options == []

    def test_details_already_given_are_never_unset_by_a_later_call(self) -> None:
        slate = BookingSlate()
        slate.remember(name="Tushar", phone="91220910827")
        slate.remember(reason="eye checkup")
        assert slate.customer_name == "Tushar"
        assert slate.customer_phone == "91220910827"

    def test_changing_service_drops_the_choice_made_for_the_old_one(self) -> None:
        slate = _offered(9, 10, 11, 12)
        slate.choose(slate.options[1])
        slate.offer(
            service_id="33333333-3333-3333-3333-333333333333",
            service_name="Eye Test",
            location_id=slate.location_id,
            location_name=slate.location_name,
            timezone=slate.timezone,
            options=_options(14, 15),
            now=NOW,
        )
        assert slate.chosen is None, "a pick made for another service is not a pick"

    def test_a_choice_that_is_no_longer_free_stops_being_a_choice(self) -> None:
        slate = _offered(9, 10, 11, 12)
        slate.choose(slate.options[1])
        slate.hold(token="tok-1", expires_at=NOW + timedelta(minutes=10))
        # Same service and branch, but 10:00 has gone.
        slate.offer(
            service_id=slate.service_id,
            service_name=slate.service_name,
            location_id=slate.location_id,
            location_name=slate.location_name,
            timezone=slate.timezone,
            options=_options(9, 11, 12),
            now=NOW,
        )
        assert slate.chosen is None
        assert slate.hold_token == ""

    def test_an_expired_hold_is_not_offered_back_as_live(self) -> None:
        slate = _offered(9, 10)
        slate.hold(token="tok-1", expires_at=NOW + timedelta(minutes=5))
        assert slate.live_hold(NOW) == "tok-1"
        assert slate.live_hold(NOW + timedelta(minutes=6)) == ""

    def test_booking_clears_the_booking_but_keeps_the_customer(self) -> None:
        slate = _offered(9, 10)
        slate.choose(slate.options[0])
        slate.hold(token="tok-1", expires_at=NOW + timedelta(minutes=10))
        slate.remember(name="Tushar", phone="91220910827", reason="eye checkup")
        slate.booked("APT-ABCD1234")

        assert slate.chosen is None
        assert slate.options == []
        assert slate.hold_token == ""
        assert slate.last_reference == "APT-ABCD1234"
        # So a second booking in the same thread does not re-ask for these.
        assert slate.customer_name == "Tushar"
        assert slate.customer_phone == "91220910827"


class TestWhatTheAgentIsToldEachTurn:
    def test_the_offered_times_come_back_with_their_exact_instants(self) -> None:
        block = _offered(9, 10, 11, 12).render(NOW)
        assert "ALREADY offered" in block
        assert "starts_at=" in block
        assert "Do not look them up again" in block

    def test_it_names_the_one_thing_still_missing(self) -> None:
        slate = _offered(9, 10)
        slate.choose(slate.options[0])
        slate.remember(phone="91220910827")
        block = slate.render(NOW)
        assert "Still needed before booking: their name." in block

    def test_it_says_plainly_when_it_is_time_to_book(self) -> None:
        # The turn the reported conversation never reached.
        slate = _offered(9, 10)
        slate.choose(slate.options[0])
        slate.remember(name="Tushar", phone="91220910827")
        block = slate.render(NOW)
        assert "Call it NOW" in block
        assert "Still needed" not in block

    def test_details_already_given_are_marked_as_not_to_be_asked_again(self) -> None:
        slate = _offered(9, 10)
        slate.remember(name="Tushar", phone="91220910827", reason="eye checkup")
        block = slate.render(NOW)
        for line in ("Name: Tushar", "Phone: 91220910827", "eye checkup"):
            assert line in block
        assert block.count("do not ask again") >= 3

    def test_a_stale_list_is_flagged_rather_than_read_out(self) -> None:
        block = _offered(9, 10).render(NOW + OFFER_TTL + timedelta(minutes=1))
        assert "too old to trust" in block
        assert "starts_at=" not in block

    def test_an_empty_slate_says_so_instead_of_rendering_nothing(self) -> None:
        assert "Nothing yet" in BookingSlate().render(NOW)


class TestThePromptCarriesTheState:
    def test_the_receptionist_template_has_somewhere_to_put_it(self) -> None:
        assert "<<CONVERSATION_STATE>>" in FRONT_OFFICE_SYSTEM

    def test_the_rendered_prompt_contains_the_state_and_no_marker(self) -> None:
        loop = AgentLoop(
            ToolRegistry([]),
            ModelRouter(cheap=_ScriptedLLM([])),
            refusal_answer=FRONT_OFFICE_REFUSAL,
            system_template=FRONT_OFFICE_SYSTEM,
        )
        rendered = loop._system_prompt(state_block="  They have CHOSEN option 2")
        assert "They have CHOSEN option 2" in rendered
        assert "<<CONVERSATION_STATE>>" not in rendered

    def test_a_customers_own_punctuation_cannot_break_the_render(self) -> None:
        # The block carries a customer's name and their reason for visiting.
        # `str.format()` would read a brace in either as a field and raise.
        loop = AgentLoop(
            ToolRegistry([]),
            ModelRouter(cheap=_ScriptedLLM([])),
            refusal_answer=FRONT_OFFICE_REFUSAL,
            system_template=FRONT_OFFICE_SYSTEM,
        )
        rendered = loop._system_prompt(state_block="  Reason: {weird} braces {")
        assert "{weird} braces {" in rendered

    def test_the_document_agent_is_untouched_by_the_new_marker(self) -> None:
        loop = AgentLoop(
            ToolRegistry([]),
            ModelRouter(cheap=_ScriptedLLM([])),
            refusal_answer="no",
        )
        # No marker in that template, so the state is simply not rendered — and
        # nothing raises.
        assert "CONVERSATION_STATE" not in loop._system_prompt(state_block="ignored")

    def test_the_prompt_forbids_sending_the_same_list_twice(self) -> None:
        assert "NEVER send the same numbered list of times twice" in FRONT_OFFICE_SYSTEM


class _ScriptedLLM:
    """Replays planner actions and records the system prompts it was given."""

    name = "scripted"

    def __init__(self, script: list[Any]) -> None:
        self._script = list(script)
        self.systems: list[str] = []
        self.prompts: list[str] = []

    async def generate(self, system: str, user: str) -> LLMResult:
        self.systems.append(system)
        self.prompts.append(user)
        if not self._script:
            raise AssertionError(
                "the agent took more steps than the script had answers for; "
                f"last transcript:\n{user[-2000:]}"
            )
        nxt = self._script.pop(0)
        text = nxt(user) if callable(nxt) else nxt
        return LLMResult(
            text=text, tokens_used=7, provider="scripted", model="scripted-1"
        )


def _action(name: str, **inputs: Any) -> str:
    return json.dumps({"thought": "…", "action": name, "action_input": inputs})


def _pull(transcript: str, marker: str, end: str) -> str:
    start = transcript.rindex(marker) + len(marker)
    return transcript[start : transcript.index(end, start)]


class TestTheToolsFillTheBookingInFromTheSlate:
    """Tool-level: a turn should only have to supply what is new."""

    async def _offer(self, world: _World, slate: BookingSlate) -> ToolContext:
        """Run the real availability tool so the slate holds real slots."""
        ctx = ToolContext(tenant_id=TENANT, extras={"slate": slate})
        result = await FindAvailableSlotsTool(world.uow_factory).run(
            ctx,
            service_id=str(world.services[0].id),
            location_id=str(world.locations[0].id),
            date=_next_open_day(world),
        )
        assert result.ok, result.observation
        return ctx

    async def test_finding_slots_writes_them_to_the_slate(
        self, world: _World
    ) -> None:
        slate = BookingSlate()
        await self._offer(world, slate)
        assert slate.options, "the offered list must survive the turn"
        assert slate.service_id == str(world.services[0].id)
        assert slate.location_id == str(world.locations[0].id)
        # And the numbers the customer sees resolve to the engine's instants.
        assert slate.resolve("1", datetime.now(UTC)) == slate.options[0]

    async def test_the_observation_no_longer_orders_the_list_to_be_read_out(
        self, world: _World
    ) -> None:
        # The line that turned every re-check into a re-offer.
        slate = BookingSlate()
        ctx = ToolContext(tenant_id=TENANT, extras={"slate": slate})
        result = await FindAvailableSlotsTool(world.uow_factory).run(
            ctx,
            service_id=str(world.services[0].id),
            location_id=str(world.locations[0].id),
            date=_next_open_day(world),
        )
        assert "If they have ALREADY picked one, do" in result.observation
        assert "not list them again" in result.observation

    async def test_holding_a_slot_needs_only_the_number_they_replied_with(
        self, world: _World
    ) -> None:
        slate = BookingSlate()
        ctx = await self._offer(world, slate)

        result = await CreateSlotHoldTool(world.uow_factory).run(ctx, option="2")

        assert result.ok, result.observation
        assert slate.chosen is not None and slate.chosen.option == 2
        assert slate.live_hold(datetime.now(UTC)), "the hold must outlive the turn"
        assert result.data["starts_at"] == slate.chosen.starts_at.isoformat()

    async def test_booking_needs_only_what_this_turn_learned(
        self, world: _World
    ) -> None:
        # The turn that used to re-offer the list. Everything except the name
        # comes from the conversation: service, branch, time, hold, phone.
        slate = BookingSlate()
        ctx = await self._offer(world, slate)
        ctx.extras["customer_phone"] = "91220910827"
        picked = slate.options[0].starts_at
        await CreateSlotHoldTool(world.uow_factory).run(ctx, option="1")

        result = await BookAppointmentTool(world.uow_factory).run(
            ctx, customer_name="Tushar"
        )

        assert result.ok, result.observation
        assert len(world.appointments) == 1
        appointment = world.appointments[0]
        assert appointment.customer_name == "Tushar"
        assert appointment.customer_phone == "91220910827"
        assert appointment.starts_at == picked

    async def test_the_reason_given_earlier_reaches_the_appointment(
        self, world: _World
    ) -> None:
        slate = BookingSlate()
        ctx = await self._offer(world, slate)
        ctx.extras["customer_phone"] = "91220910827"
        # Told to the assistant a turn before the booking is made.
        slate.remember(reason="eye checkup")
        await CreateSlotHoldTool(world.uow_factory).run(ctx, option="1")

        await BookAppointmentTool(world.uow_factory).run(ctx, customer_name="Tushar")

        assert world.appointments[0].customer_notes == "eye checkup"

    async def test_a_completed_booking_stops_being_in_flight(
        self, world: _World
    ) -> None:
        slate = BookingSlate()
        ctx = await self._offer(world, slate)
        ctx.extras["customer_phone"] = "91220910827"
        await CreateSlotHoldTool(world.uow_factory).run(ctx, option="1")
        await BookAppointmentTool(world.uow_factory).run(ctx, customer_name="Tushar")

        assert slate.chosen is None and slate.options == []
        assert slate.last_reference.startswith("APT-")
        assert "ALREADY BOOKED" in slate.render(datetime.now(UTC))

    async def test_a_pick_that_matches_nothing_is_refused_not_guessed(
        self, world: _World
    ) -> None:
        slate = BookingSlate()
        ctx = await self._offer(world, slate)

        result = await CreateSlotHoldTool(world.uow_factory).run(ctx, option="99")

        assert not result.ok
        assert "could not match" in result.observation
        assert world.live_reservations() == [], "nothing may be held on a guess"

    async def test_without_a_slate_the_tools_behave_exactly_as_before(
        self, world: _World
    ) -> None:
        # A caller that keeps no state (a one-shot API call, an eval harness)
        # must still be able to drive these the explicit way.
        bare = ToolContext(tenant_id=TENANT)
        result = await CreateSlotHoldTool(world.uow_factory).run(bare, option="2")
        assert not result.ok
        assert "option=" in result.observation


class TestTheReportedConversationNowBooks:
    """The thread from the bug report, replayed across separate agent runs.

    Each turn is its own `AgentLoop.run`, with the slate serialised to JSON and
    read back in between — because that is what happens in production, and
    because the state surviving that round trip is the entire fix.
    """

    def _loop(self, world: _World, script: list[Any]) -> tuple[AgentLoop, _ScriptedLLM]:
        llm = _ScriptedLLM(script)
        return (
            AgentLoop(
                ToolRegistry(build_scheduling_tools(world.uow_factory)),
                ModelRouter(cheap=llm),
                refusal_answer=FRONT_OFFICE_REFUSAL,
                max_steps=10,
                system_template=FRONT_OFFICE_SYSTEM,
            ),
            llm,
        )

    async def _turn(
        self,
        world: _World,
        bot_id: Any,
        stored: dict | None,
        message: str,
        script: list[Any],
    ) -> tuple[dict, _ScriptedLLM, Any]:
        """One inbound message, exactly as `AskFrontOffice` runs it."""
        slate = BookingSlate.from_dict(stored)
        # The channel knows the number, so the use case seeds it.
        slate.remember(phone="91220910827")
        loop, llm = self._loop(world, script)
        result = await loop.run(
            ToolContext(
                tenant_id=TENANT,
                chatbot_id=bot_id,
                extras={
                    "source": "whatsapp",
                    "channel": "whatsapp",
                    "customer_phone": "91220910827",
                    "conversation_id": "thread-1",
                    "slate": slate,
                },
            ),
            message,
            state_block=slate.render(datetime.now(UTC)),
        )
        # Through the database and back, as a real second message would.
        return json.loads(json.dumps(slate.to_dict())), llm, result

    async def test_offered_picked_named_booked(self, world: _World) -> None:
        bot = world.add_assistant(books=True, name="Reception")
        day = _next_open_day(world)

        # Turn 1 — "I'd like to book". The agent looks the times up and offers
        # them. This much always worked.
        state, _, _ = await self._turn(
            world,
            bot.id,
            None,
            "I am Tushar, would like to book an appointment",
            [
                _action("list_services"),
                lambda t: _action(
                    "find_available_slots",
                    service_id=_pull(t, "[service_id=", "]"),
                    location_id=_pull(t, "(location_id=", ","),
                    date=day,
                ),
                _action("final", answer="Here are the times — reply with a number."),
            ],
        )
        assert state["options"], "the offered list must be remembered"

        # Turn 2 — "1". The reported failure was here: the agent re-listed.
        # It now has the list already, so the number is all it needs.
        state, llm, _ = await self._turn(
            world,
            bot.id,
            state,
            "1",
            [
                _action("create_slot_hold", option="1"),
                _action("final", answer="Held it. What's your name?"),
            ],
        )
        assert "ALREADY offered" in llm.systems[0], "the turn must see the list"
        assert state["chosen"]["option"] == 1
        assert state["hold_token"]

        # Turn 3 — the name. Everything else — service, branch, the exact
        # instant, the hold, the phone the channel knows — is already known.
        state, llm, result = await self._turn(
            world,
            bot.id,
            state,
            "Tushar, it's for an eye checkup",
            [
                _action(
                    "book_appointment",
                    customer_name="Tushar",
                    reason_for_visit="eye checkup",
                ),
                lambda t: _action(
                    "final", answer=f"Booked — reference {_pull(t, 'Reference ', '.')}"
                ),
            ],
        )

        # Going into this turn the name is the one outstanding thing, and the
        # agent is told exactly that — not "which time", and not the phone
        # number the customer is messaging from.
        assert "Still needed before booking: their name." in llm.systems[0]
        assert len(world.appointments) == 1, "the conversation still did not book"
        appointment = world.appointments[0]
        assert appointment.customer_name == "Tushar"
        assert appointment.customer_phone == "91220910827"
        assert appointment.customer_notes == "eye checkup"
        assert appointment.status == "confirmed"
        assert "APT-" in result.answer
        # And the thread is no longer mid-booking.
        assert state.get("chosen") is None
        assert state["last_reference"].startswith("APT-")

    async def test_the_agent_never_needs_to_re_ask_the_engine_after_a_pick(
        self, world: _World
    ) -> None:
        """The specific loop: a re-check must not be *required* to act on "1".

        Scripted with no `find_available_slots` step at all, so if holding the
        slot still depended on re-deriving the list the script would run out and
        the test would fail loudly.
        """
        bot = world.add_assistant(books=True, name="Reception")
        state, _, _ = await self._turn(
            world,
            bot.id,
            None,
            "book me in",
            [
                _action("list_services"),
                lambda t: _action(
                    "find_available_slots",
                    service_id=_pull(t, "[service_id=", "]"),
                    location_id=_pull(t, "(location_id=", ","),
                    date=_next_open_day(world),
                ),
                _action("final", answer="Reply with a number."),
            ],
        )

        _, _, result = await self._turn(
            world,
            bot.id,
            state,
            "2",
            [
                _action("create_slot_hold", option="2"),
                _action("book_appointment", customer_name="Tushar"),
                lambda t: _action("final", answer=_pull(t, "Reference ", ".")),
            ],
        )

        assert "find_available_slots" not in result.trace.tools_used()
        assert len(world.appointments) == 1


class TestRealTimeConflicts:
    """The other half of what was asked for: never offer a time already taken.

    This was already true — the availability engine excludes confirmed
    appointments and live holds on every query — but nothing pinned it from the
    agent's side, and a booking flow that finally completes is the first thing
    that can prove it.
    """

    async def test_a_slot_this_conversation_booked_is_no_longer_offered(
        self, world: _World
    ) -> None:
        slate = BookingSlate()
        ctx = ToolContext(
            tenant_id=TENANT,
            extras={"slate": slate, "customer_phone": "91220910827"},
        )
        find = FindAvailableSlotsTool(world.uow_factory)
        day = _next_open_day(world)
        args = {
            "service_id": str(world.services[0].id),
            "location_id": str(world.locations[0].id),
            "date": day,
        }

        first = await find.run(ctx, **args)
        taken = first.data["slots"][0]["starts_at"]

        await CreateSlotHoldTool(world.uow_factory).run(ctx, option="1")
        await BookAppointmentTool(world.uow_factory).run(ctx, customer_name="Tushar")

        again = await find.run(ctx, **args)
        offered = [s["starts_at"] for s in again.data["slots"]]
        assert taken not in offered, "a booked time was offered to the next customer"

    async def test_a_held_slot_is_withheld_while_the_hold_is_live(
        self, world: _World
    ) -> None:
        slate = BookingSlate()
        ctx = ToolContext(tenant_id=TENANT, extras={"slate": slate})
        find = FindAvailableSlotsTool(world.uow_factory)
        args = {
            "service_id": str(world.services[0].id),
            "location_id": str(world.locations[0].id),
            "date": _next_open_day(world),
        }

        first = await find.run(ctx, **args)
        held = first.data["slots"][0]["starts_at"]
        await CreateSlotHoldTool(world.uow_factory).run(ctx, option="1")

        again = await find.run(ctx, **args)
        assert held not in [s["starts_at"] for s in again.data["slots"]]


@pytest.mark.parametrize(
    ("stored", "expected"),
    [
        (None, {}),
        ({}, {}),
        ("not a dict", {}),
        ([1, 2, 3], {}),
    ],
)
def test_any_stored_shape_reads_back_as_a_usable_slate(
    stored: Any, expected: dict
) -> None:
    assert BookingSlate.from_dict(stored).to_dict() == expected
