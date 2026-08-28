"""Appointment domain events.

Collected on the unit of work and dispatched after commit, exactly like the
existing chat/document events. Two things follow for free from the current bus
(`infrastructure/messaging/event_bus.py`): every event is persisted to
`audit_events`, which is the substrate for the audit trail in spec section 40;
and later phases (reminders, webhooks, calendar sync, analytics) subscribe here
rather than being wired into the booking use case — which is spec section 49.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime

from src.domain.shared.events import DomainEvent


@dataclass(frozen=True, kw_only=True)
class AppointmentCreated(DomainEvent):
    appointment_id: uuid.UUID
    location_id: uuid.UUID
    service_id: uuid.UUID
    starts_at: datetime
    # Carried on the event so the channel-attribution report (section 44) never
    # has to join back to the appointment row.
    source: str
    status: str


@dataclass(frozen=True, kw_only=True)
class AppointmentStatusChanged(DomainEvent):
    """One event covers confirm, check-in, complete, no-show and cancel.

    A separate class per status would multiply handlers that all do the same
    thing; subscribers that care about one transition filter on `to_status`.
    """

    appointment_id: uuid.UUID
    from_status: str
    to_status: str
    actor_kind: str
    reason: str = ""


@dataclass(frozen=True, kw_only=True)
class AppointmentRescheduled(DomainEvent):
    appointment_id: uuid.UUID
    # The previous time is on the event because a reschedule notification has to
    # say what moved, and by then the row holds only the new time.
    previous_starts_at: datetime
    starts_at: datetime
    actor_kind: str
    reason: str = ""
