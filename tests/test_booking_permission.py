"""Only the assistant the operator allowed to book can book.

The permission is a single switch on one assistant (`appointments_enabled`), and
the failure it guards against is not subtle: a second assistant in the same
workspace quietly taking bookings, or cancelling somebody's appointment, because
it happened to be built on a loop that carries the scheduling tools.

Routing alone cannot promise that. `chat.py`, `public.py` and `whatsapp_web.py`
each choose the booking agent by reading the flag, but the shared document agent
*also* registers these tools whenever `APPOINTMENT_AGENT_TOOLS_ENABLED` is on —
for every assistant in the deployment. So the check lives at the tool, which is
the one place every path has to go through, and these tests pin it there.
"""

from __future__ import annotations

from typing import Any

import pytest
from src.application.agent.tools import ToolContext, ToolResult, ToolSpec
from src.domain.chatbot.entities import AssistantConfig, Chatbot
from src.domain.shared.identifiers import ChatbotId, TenantId, new_id
from src.infrastructure.agent.scheduling_tools import (
    BOOKING_NOT_PERMITTED,
    BookingPermissionGate,
    build_scheduling_tools,
)

TENANT = TenantId(new_id())
OTHER_TENANT = TenantId(new_id())


class _SpyTool:
    """A stand-in for a real scheduling tool that records being reached.

    The assertion that matters is not what the gate returns — it is that a
    forbidden call never arrives at the thing that would have booked.
    """

    spec = ToolSpec(
        name="book_appointment",
        description="Books something real.",
        parameters={"customer_name": {"type": "string"}},
    )

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def run(self, ctx: ToolContext, **kwargs: Any) -> ToolResult:
        self.calls.append(kwargs)
        return ToolResult(observation="Booked.", data={"reference": "APT-12345678"})


class _FakeChatbots:
    def __init__(self, bots: dict[ChatbotId, Chatbot]) -> None:
        self._bots = bots

    async def get(self, tenant_id, chatbot_id):  # type: ignore[no-untyped-def]
        bot = self._bots.get(chatbot_id)
        return bot if bot and bot.tenant_id == tenant_id else None


class _FakeUow:
    def __init__(self, bots: dict[ChatbotId, Chatbot]) -> None:
        self.chatbots = _FakeChatbots(bots)
        self.scoped_to: TenantId | None = None

    async def __aenter__(self) -> _FakeUow:
        return self

    async def __aexit__(self, *args: object) -> None:
        return None

    def set_tenant_scope(self, tenant_id) -> None:  # type: ignore[no-untyped-def]
        self.scoped_to = tenant_id


def _assistant(*, books: bool, tenant: TenantId = TENANT) -> Chatbot:
    return Chatbot(
        tenant_id=tenant,
        name="Receptionist" if books else "Support bot",
        assistant=AssistantConfig(appointments_enabled=books),
    )


@pytest.fixture
def world():  # type: ignore[no-untyped-def]
    booker = _assistant(books=True)
    bystander = _assistant(books=False)
    bots = {booker.id: booker, bystander.id: bystander}

    class _World:
        def __init__(self) -> None:
            self.booker = booker
            self.bystander = bystander

        def uow_factory(self) -> _FakeUow:
            return _FakeUow(bots)

    return _World()


class TestOnlyTheAllowedAssistantReachesTheTool:
    async def test_the_permitted_assistant_gets_through(self, world) -> None:  # type: ignore[no-untyped-def]
        spy = _SpyTool()
        gate = BookingPermissionGate(spy, world.uow_factory)

        result = await gate.run(
            ToolContext(tenant_id=TENANT, chatbot_id=world.booker.id),
            customer_name="Aisha",
        )

        assert result.ok
        assert spy.calls == [{"customer_name": "Aisha"}]

    async def test_an_assistant_without_permission_never_reaches_the_tool(
        self, world
    ) -> None:  # type: ignore[no-untyped-def]
        spy = _SpyTool()
        gate = BookingPermissionGate(spy, world.uow_factory)

        result = await gate.run(
            ToolContext(tenant_id=TENANT, chatbot_id=world.bystander.id),
            customer_name="Aisha",
        )

        assert not result.ok
        assert result.observation == BOOKING_NOT_PERMITTED
        assert spy.calls == [], "a forbidden assistant reached the booking tool"

    async def test_turning_the_switch_off_takes_the_capability_away(
        self, world
    ) -> None:  # type: ignore[no-untyped-def]
        # Permission is read per call, not captured when the agent was built —
        # otherwise a running process keeps booking after the operator has
        # switched it off, until the next deploy.
        spy = _SpyTool()
        gate = BookingPermissionGate(spy, world.uow_factory)
        ctx = ToolContext(tenant_id=TENANT, chatbot_id=world.booker.id)

        assert (await gate.run(ctx)).ok
        world.booker.assistant.appointments_enabled = False
        assert not (await gate.run(ctx)).ok
        assert len(spy.calls) == 1

    async def test_a_context_with_no_assistant_is_refused(self, world) -> None:  # type: ignore[no-untyped-def]
        # Nothing was given permission, so nothing has it. Staff bookings do not
        # come through the agent — they go through the appointments API, which
        # carries a real principal.
        spy = _SpyTool()
        gate = BookingPermissionGate(spy, world.uow_factory)

        result = await gate.run(ToolContext(tenant_id=TENANT))

        assert not result.ok
        assert spy.calls == []

    async def test_another_tenants_assistant_id_is_refused(self, world) -> None:  # type: ignore[no-untyped-def]
        # The lookup is tenant-scoped, so a booking assistant's id borrowed into
        # another workspace resolves to nothing rather than to permission.
        spy = _SpyTool()
        gate = BookingPermissionGate(spy, world.uow_factory)

        result = await gate.run(
            ToolContext(tenant_id=OTHER_TENANT, chatbot_id=world.booker.id)
        )

        assert not result.ok
        assert spy.calls == []

    async def test_the_refusal_tells_the_planner_not_to_improvise(self) -> None:
        # An agent told only "denied" invents the booking instead. The wording
        # is the part that stops it, so it is pinned.
        assert "do NOT tell the customer anything is booked" in BOOKING_NOT_PERMITTED
        assert "Do NOT offer a time" in BOOKING_NOT_PERMITTED


class TestEverySchedulingToolIsGated:
    """The property that makes the guarantee hold as tools are added.

    Gating six of seven tools is the same bug as gating none: whichever one is
    forgotten is the one that leaks. `build_scheduling_tools` is the only place
    these are constructed, so "everything it returns is a gate" is checkable.
    """

    def test_nothing_leaves_the_factory_ungated(self) -> None:
        tools = build_scheduling_tools(lambda: None)
        assert tools, "the factory returned no tools at all"
        ungated = [t.spec.name for t in tools if not isinstance(t, BookingPermissionGate)]
        assert ungated == [], f"these tools can be called without permission: {ungated}"

    def test_the_read_only_tools_are_gated_too(self) -> None:
        # Reading a customer's upcoming appointments, or quoting the branch's
        # free slots, is not a lesser capability — it is the same customer data.
        names = {t.spec.name for t in build_scheduling_tools(lambda: None)}
        assert {"list_services", "find_available_slots", "find_customer_appointments"} <= names

    def test_the_planner_catalogue_is_unchanged_by_the_gate(self) -> None:
        # The gate proxies `spec`, so every prompt written against the tool
        # descriptions still says exactly what it said before.
        spy = _SpyTool()
        gate = BookingPermissionGate(spy, lambda: None)
        assert gate.spec is spy.spec
