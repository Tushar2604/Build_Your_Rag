"""What a domain event may carry, and what happens when the audit write fails.

Both cases here are regressions from a real bug. `AppointmentCreated` was the
first event to carry a `datetime`, and the audit serializer only understood
UUIDs — so the INSERT raised. Because events are dispatched AFTER the business
transaction commits, that turned a booking which had genuinely succeeded into a
500 the caller then retried.

Hermetic: `_serialize` is pure, and the publish path is exercised with a stubbed
audit writer rather than a database.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime

import pytest
from src.domain.scheduling.events import (
    AppointmentCreated,
    AppointmentRescheduled,
    AppointmentStatusChanged,
)
from src.domain.shared.events import DomainEvent
from src.infrastructure.messaging.event_bus import InProcessEventBus, _serialize

TENANT = uuid.uuid4()
MOMENT = datetime(2026, 9, 1, 15, 0, tzinfo=UTC)


def _appointment_created() -> AppointmentCreated:
    return AppointmentCreated(
        tenant_id=TENANT,
        appointment_id=uuid.uuid4(),
        location_id=uuid.uuid4(),
        service_id=uuid.uuid4(),
        starts_at=MOMENT,
        source="whatsapp",
        status="confirmed",
    )


class TestSerialization:
    def test_an_event_carrying_a_datetime_is_json_serializable(self) -> None:
        # The exact regression: this raised "Object of type datetime is not JSON
        # serializable" on the audit INSERT.
        payload = _serialize(_appointment_created())
        json.dumps(payload)  # must not raise
        assert payload["starts_at"] == MOMENT.isoformat()

    def test_uuids_still_become_strings(self) -> None:
        payload = _serialize(_appointment_created())
        assert isinstance(payload["appointment_id"], str)
        uuid.UUID(payload["appointment_id"])  # a round-trippable id, not a repr

    @pytest.mark.parametrize(
        "event",
        [
            _appointment_created(),
            AppointmentStatusChanged(
                tenant_id=TENANT,
                appointment_id=uuid.uuid4(),
                from_status="pending",
                to_status="confirmed",
                actor_kind="customer",
                reason="Replied YES",
            ),
            AppointmentRescheduled(
                tenant_id=TENANT,
                appointment_id=uuid.uuid4(),
                previous_starts_at=MOMENT,
                starts_at=MOMENT,
                actor_kind="staff",
            ),
        ],
    )
    def test_every_scheduling_event_survives_the_audit_serializer(
        self, event: DomainEvent
    ) -> None:
        json.dumps(_serialize(event))

    def test_nested_collections_are_coerced_too(self) -> None:
        # A later event carrying a list of resource ids must not reintroduce the
        # same failure one level down.
        @dataclass(frozen=True, kw_only=True)
        class WithCollections(DomainEvent):
            ids: list[uuid.UUID]
            marks: dict[str, datetime]
            day: date

        payload = _serialize(
            WithCollections(
                tenant_id=TENANT,
                ids=[uuid.uuid4()],
                marks={"at": MOMENT},
                day=MOMENT.date(),
            )
        )
        json.dumps(payload)
        assert isinstance(payload["ids"][0], str)
        assert payload["marks"]["at"] == MOMENT.isoformat()

    def test_an_unknown_type_is_left_alone(self) -> None:
        # Passing it through means an unconsidered field fails loudly at the
        # INSERT rather than being silently stringified into something nobody
        # can parse back.
        @dataclass(frozen=True, kw_only=True)
        class Odd(DomainEvent):
            thing: object

        payload = _serialize(Odd(tenant_id=TENANT, thing={1, 2}))
        with pytest.raises(TypeError):
            json.dumps(payload)


class TestPublishNeverFailsACommittedWrite:
    async def test_a_broken_audit_write_does_not_propagate(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Events dispatch after commit, so raising here would 500 a booking
        that actually succeeded — and the caller would retry a write that had
        already happened."""
        bus = InProcessEventBus()

        async def explode(_event: DomainEvent) -> None:
            raise RuntimeError("database is on fire")

        monkeypatch.setattr(bus, "_persist_audit", explode)
        await bus.publish(_appointment_created())  # must not raise

    async def test_handlers_still_run_when_the_audit_write_fails(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Reminders and webhooks hang off these handlers in later phases; losing
        # them because an audit row could not be written would be the wrong
        # trade entirely.
        bus = InProcessEventBus()
        seen: list[str] = []

        async def explode(_event: DomainEvent) -> None:
            raise RuntimeError("database is on fire")

        async def handler(event: DomainEvent) -> None:
            seen.append(event.name)

        monkeypatch.setattr(bus, "_persist_audit", explode)
        bus.subscribe("AppointmentCreated", handler)
        await bus.publish(_appointment_created())
        assert seen == ["AppointmentCreated"]

    async def test_one_failing_handler_does_not_stop_the_others(self) -> None:
        bus = InProcessEventBus()
        seen: list[str] = []

        async def noop_audit(_event: DomainEvent) -> None:
            return None

        async def bad(_event: DomainEvent) -> None:
            raise RuntimeError("nope")

        async def good(event: DomainEvent) -> None:
            seen.append(event.name)

        bus._persist_audit = noop_audit  # type: ignore[method-assign]
        bus.subscribe("AppointmentCreated", bad)
        bus.subscribe("AppointmentCreated", good)
        await bus.publish(_appointment_created())
        assert seen == ["AppointmentCreated"]
