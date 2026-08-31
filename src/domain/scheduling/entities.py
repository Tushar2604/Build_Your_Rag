"""Scheduling entities: what can be booked, by whom, where, and when.

Deliberately generic. A "resource" is a doctor, a consultant, a treatment room,
a vehicle, or a machine — the availability engine treats them identically, and a
service can require several at once (a dentist *and* a chair). Modelling staff as
a special case is what makes a scheduler unable to book a meeting room later.

Times: every instant on these entities is timezone-aware UTC. The one exception
is `AvailabilityRule`, which stores wall-clock local times because "Mondays 9-5"
survives a daylight-saving change and a stored UTC offset does not. See
`availability.py` for where the two are reconciled.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, time, timedelta
from typing import Literal, get_args
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from src.domain.shared.errors import InvalidStateError
from src.domain.shared.identifiers import (
    AppointmentId,
    AvailabilityRuleId,
    BlockedPeriodId,
    LocationId,
    ResourceId,
    ServiceId,
    TenantId,
    UserId,
    new_id,
)

# --- Appointment lifecycle (spec section 7) ---------------------------------

AppointmentStatus = Literal[
    "draft",
    "requested",
    "pending",
    "awaiting_confirmation",
    "confirmed",
    "arrived",
    "checked_in",
    "in_progress",
    "completed",
    "cancelled",
    "no_show",
    "rescheduled",
    "waitlisted",
]
ALL_STATUSES: tuple[AppointmentStatus, ...] = get_args(AppointmentStatus)

# Statuses that no longer occupy their slot. A cancelled or rescheduled
# appointment must release its reservation, or the slot stays dead forever.
RELEASING_STATUSES: frozenset[str] = frozenset({"cancelled", "no_show", "rescheduled"})

# Nothing follows these. Kept explicit rather than derived so a new status
# cannot silently become re-openable.
TERMINAL_STATUSES: frozenset[str] = frozenset(
    {"completed", "cancelled", "no_show", "rescheduled"}
)

# The transition table. An appointment's history is the product's audit trail
# (spec section 40), so transitions are validated here rather than wherever a
# router happens to set a field.
_TRANSITIONS: dict[str, frozenset[str]] = {
    "draft": frozenset({"requested", "pending", "confirmed", "cancelled"}),
    "requested": frozenset(
        {"pending", "awaiting_confirmation", "confirmed", "cancelled", "waitlisted"}
    ),
    "pending": frozenset(
        {"awaiting_confirmation", "confirmed", "cancelled", "waitlisted"}
    ),
    "awaiting_confirmation": frozenset(
        {"confirmed", "cancelled", "no_show", "rescheduled", "waitlisted"}
    ),
    "confirmed": frozenset(
        {
            "arrived",
            "checked_in",
            "in_progress",
            "completed",
            "cancelled",
            "no_show",
            "rescheduled",
        }
    ),
    "arrived": frozenset({"checked_in", "in_progress", "completed", "cancelled", "no_show"}),
    "checked_in": frozenset({"in_progress", "completed", "cancelled", "no_show"}),
    "in_progress": frozenset({"completed", "cancelled"}),
    "waitlisted": frozenset({"requested", "pending", "confirmed", "cancelled"}),
    # Terminal.
    "completed": frozenset(),
    "cancelled": frozenset(),
    "no_show": frozenset(),
    "rescheduled": frozenset(),
}

# --- Booking source (spec section 44) ---------------------------------------

BookingSource = Literal[
    "staff",
    "ai_voice",
    "whatsapp",
    "web_widget",
    "booking_page",
    "sms",
    "email",
    "mobile_app",
    "portal",
    "api",
    "campaign",
]
ALL_SOURCES: tuple[BookingSource, ...] = get_args(BookingSource)

# Who caused a change. Kept separate from `BookingSource`: the source is where
# the appointment came from and never changes; the actor is who touched it this
# time, and a staff member can cancel an appointment an AI created.
ActorKind = Literal["staff", "customer", "ai_agent", "system"]

# What a resource *is*. The availability engine ignores this — it exists for the
# UI (grouping, icons, filters) and for service eligibility roles.
ResourceKind = Literal["staff", "room", "equipment", "vehicle", "other"]
ALL_RESOURCE_KINDS: tuple[ResourceKind, ...] = get_args(ResourceKind)

# Who an availability rule or a block belongs to.
OwnerKind = Literal["location", "resource"]

MAX_NAME = 160
MAX_NOTES = 4000
# A day has 1440 minutes; a service longer than that needs multi-day booking,
# which is a different product.
MAX_DURATION_MINUTES = 1440
MAX_BUFFER_MINUTES = 480


def is_valid_timezone(name: str) -> bool:
    """True when `name` is a real IANA zone on this machine.

    Validated on the way in rather than at booking time: an unknown zone stored
    on a location turns every later availability query for that branch into an
    exception, far from the typo that caused it.
    """
    try:
        ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        return False
    return True


def can_transition(current: str, target: str) -> bool:
    return target in _TRANSITIONS.get(current, frozenset())


@dataclass
class Location:
    """A branch. Owns its own timezone, hours, and contact details (section 34)."""

    tenant_id: TenantId
    name: str
    id: LocationId = field(default_factory=lambda: LocationId(new_id()))
    # IANA name ("Asia/Dubai"), never a UTC offset: offsets are wrong for half
    # the year anywhere that observes daylight saving.
    timezone: str = "UTC"
    address: str = ""
    phone: str = ""
    email: str = ""
    is_active: bool = True
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def validation_error(self) -> str | None:
        if not self.name.strip():
            return "A location name is required."
        if not is_valid_timezone(self.timezone):
            return f"{self.timezone!r} isn't a recognised IANA timezone."
        return None

    def normalized(self) -> Location:
        self.name = self.name.strip()[:MAX_NAME]
        self.address = self.address.strip()
        return self


@dataclass
class Service:
    """Something a customer books (section 9).

    Buffers are part of the service, not the appointment: the ten minutes after
    a consultation are needed whoever books it, and putting them on the
    appointment lets a booking path forget them.
    """

    tenant_id: TenantId
    name: str
    duration_minutes: int
    id: ServiceId = field(default_factory=lambda: ServiceId(new_id()))
    category: str = ""
    description: str = ""
    buffer_before_minutes: int = 0
    buffer_after_minutes: int = 0
    price_cents: int = 0
    deposit_cents: int = 0
    currency: str = "AED"
    # How soon before a slot a customer may still book it. Stops the 3pm slot
    # being bookable at 2:59pm when the room needs preparing.
    min_notice_minutes: int = 0
    # How far ahead booking is allowed. Bounds the availability query as well as
    # the business rule.
    max_horizon_days: int = 60
    # How late a customer may cancel without penalty. Recorded, not enforced
    # here — enforcement is a payments concern (section 30).
    cancellation_window_hours: int = 0
    # False = staff-only. The public booking surfaces must honour this.
    online_bookable: bool = True
    is_active: bool = True
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    @property
    def total_block_minutes(self) -> int:
        """Wall-clock time a booking actually consumes, buffers included."""
        return self.buffer_before_minutes + self.duration_minutes + self.buffer_after_minutes

    def validation_error(self) -> str | None:
        if not self.name.strip():
            return "A service name is required."
        if self.duration_minutes <= 0:
            return "Duration must be greater than zero."
        if self.duration_minutes > MAX_DURATION_MINUTES:
            return f"Duration must be {MAX_DURATION_MINUTES} minutes or less."
        if not 0 <= self.buffer_before_minutes <= MAX_BUFFER_MINUTES:
            return f"Buffer before must be between 0 and {MAX_BUFFER_MINUTES} minutes."
        if not 0 <= self.buffer_after_minutes <= MAX_BUFFER_MINUTES:
            return f"Buffer after must be between 0 and {MAX_BUFFER_MINUTES} minutes."
        if self.price_cents < 0 or self.deposit_cents < 0:
            return "Prices cannot be negative."
        if self.price_cents > 0 and self.deposit_cents > self.price_cents:
            return "A deposit cannot exceed the price."
        if self.min_notice_minutes < 0:
            return "Minimum notice cannot be negative."
        if self.max_horizon_days <= 0:
            return "The booking horizon must be at least one day."
        return None

    def normalized(self) -> Service:
        self.name = self.name.strip()[:MAX_NAME]
        self.category = self.category.strip()[:MAX_NAME]
        self.currency = (self.currency or "AED").strip().upper()[:3]
        return self


@dataclass
class Resource:
    """Anything a booking consumes: a person, a room, a machine (section 10)."""

    tenant_id: TenantId
    name: str
    id: ResourceId = field(default_factory=lambda: ResourceId(new_id()))
    kind: ResourceKind = "staff"
    location_id: LocationId | None = None
    # Set when this resource is a member of staff with a platform login, so the
    # calendar can show "my day" and notifications can reach a real person.
    user_id: UserId | None = None
    email: str = ""
    phone: str = ""
    # How many appointments this resource serves at once. 1 for a doctor; a
    # class or a group room can be higher. The database double-booking guard is
    # written for capacity 1 — see the note in `availability.py`.
    capacity: int = 1
    # Falls back to the location's zone when blank, which is the common case.
    timezone: str = ""
    color: str = ""
    is_active: bool = True
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def validation_error(self) -> str | None:
        if not self.name.strip():
            return "A resource name is required."
        if self.kind not in ALL_RESOURCE_KINDS:
            return f"{self.kind!r} isn't a supported resource type."
        if self.capacity < 1:
            return "Capacity must be at least 1."
        if self.timezone and not is_valid_timezone(self.timezone):
            return f"{self.timezone!r} isn't a recognised IANA timezone."
        return None

    def normalized(self) -> Resource:
        self.name = self.name.strip()[:MAX_NAME]
        return self


@dataclass
class ServiceResource:
    """Eligibility: this resource can serve this service, in this role.

    The `role` is what makes multi-resource booking work. A dental consultation
    needs one resource in the "practitioner" role and one in the "room" role;
    the engine picks one candidate per required role and only offers a slot when
    every role can be filled at the same instant.
    """

    tenant_id: TenantId
    service_id: ServiceId
    resource_id: ResourceId
    role: str = "primary"
    # False = this resource may serve the service but the service does not
    # require its role to be filled (an optional assistant, say).
    required: bool = True
    id: uuid.UUID = field(default_factory=new_id)


@dataclass
class AvailabilityRule:
    """A recurring weekly window of openness (section 11).

    Stored as local wall-clock time plus a weekday, NOT as UTC instants. "Open
    Mondays 09:00-17:00" means 09:00 local in January and 09:00 local in July,
    which are different UTC times. Storing UTC would silently shift every branch
    by an hour twice a year.
    """

    tenant_id: TenantId
    owner_kind: OwnerKind
    owner_id: uuid.UUID
    # Monday = 0, matching `datetime.weekday()`.
    weekday: int
    start_time: time
    end_time: time
    id: AvailabilityRuleId = field(default_factory=lambda: AvailabilityRuleId(new_id()))
    # Bounds a temporary schedule (a locum covering for three weeks). Both None
    # = the rule always applies.
    effective_from: datetime | None = None
    effective_until: datetime | None = None
    is_active: bool = True
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def validation_error(self) -> str | None:
        if not 0 <= self.weekday <= 6:
            return "Weekday must be between 0 (Monday) and 6 (Sunday)."
        if self.start_time >= self.end_time:
            return "The window must end after it starts."
        if (
            self.effective_from
            and self.effective_until
            and self.effective_from >= self.effective_until
        ):
            return "The effective period must end after it starts."
        return None


@dataclass
class BlockedPeriod:
    """Time a location or resource is unavailable: leave, a holiday, maintenance.

    An absolute UTC interval rather than a recurring rule, because that is what
    these actually are — a specific Tuesday off, not "Tuesdays off".
    """

    tenant_id: TenantId
    owner_kind: OwnerKind
    owner_id: uuid.UUID
    starts_at: datetime
    ends_at: datetime
    id: BlockedPeriodId = field(default_factory=lambda: BlockedPeriodId(new_id()))
    reason: str = ""
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def validation_error(self) -> str | None:
        if self.ends_at <= self.starts_at:
            return "A blocked period must end after it starts."
        return None


@dataclass
class StatusChange:
    """One row of an appointment's history. Append-only, never rewritten."""

    appointment_id: AppointmentId
    tenant_id: TenantId
    from_status: str
    to_status: str
    actor_kind: ActorKind
    id: uuid.UUID = field(default_factory=new_id)
    actor_id: uuid.UUID | None = None
    actor_label: str = ""
    channel: str = ""
    reason: str = ""
    occurred_at: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass
class Appointment:
    """The canonical booking. Every channel produces one of these and nothing else.

    Customer identity is carried as fields rather than a foreign key: this phase
    has no customer entity yet (see docs/appointments/architecture.md). The
    columns are named to match the CRM entity that will replace them, so the
    later migration is a backfill and not a redesign.
    """

    tenant_id: TenantId
    location_id: LocationId
    service_id: ServiceId
    starts_at: datetime
    ends_at: datetime
    customer_name: str
    id: AppointmentId = field(default_factory=lambda: AppointmentId(new_id()))
    customer_phone: str = ""
    customer_email: str = ""
    # The zone the customer was quoted in, so a confirmation can be rendered in
    # their local time rather than the branch's.
    customer_timezone: str = ""
    # The zone the appointment physically happens in. Copied from the location
    # at booking time so a later timezone correction on the branch cannot
    # retroactively move appointments that already happened.
    timezone: str = "UTC"
    status: AppointmentStatus = "pending"
    source: BookingSource = "staff"
    resource_ids: list[ResourceId] = field(default_factory=list)
    customer_notes: str = ""
    internal_notes: str = ""
    # Set when this appointment replaced another (section 14), so a reschedule
    # chain is walkable.
    rescheduled_from_id: AppointmentId | None = None
    cancellation_reason: str = ""
    # Supplied by the caller so a retried POST cannot create a second booking.
    idempotency_key: str = ""
    # When the pre-appointment reminder actually went out. NULL means it has
    # not — see migration 0028 for why this is a timestamp on the row rather
    # than a flag in the sweep's memory.
    reminder_sent_at: datetime | None = None
    created_by: UserId | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    @property
    def duration_minutes(self) -> int:
        return int((self.ends_at - self.starts_at).total_seconds() // 60)

    def needs_reminder(self, *, now: datetime, lead: timedelta) -> bool:
        """Should this appointment be reminded about, right now?

        Four conditions, and the last one is the one that matters most:

        * Nothing has been sent yet.
        * It is a live appointment — a cancelled or completed one must never
          produce a reminder, and `TERMINAL_STATUSES` is the list of those.
        * It starts within the lead time.
        * **It has not started yet.** This host sleeps and redeploys, so a
          sweep can wake up long after it should have. Without this check, a
          tick that runs an hour late tells someone about an appointment they
          are already sitting in — or already missed. A reminder that arrives
          too late is worse than one that never arrives, because it reads as a
          system that does not know what time it is.

        A booking made inside the lead time is eligible immediately and that is
        intended: someone who books for 20 minutes' time should still get the
        confirmation-shaped nudge. It is also why the message states the actual
        appointment time rather than "in 30 minutes", which would be a lie for
        exactly that booking.
        """
        if self.reminder_sent_at is not None:
            return False
        if self.status in TERMINAL_STATUSES:
            return False
        return now < self.starts_at <= now + lead

    def mark_reminded(self, *, now: datetime | None = None) -> None:
        moment = now or datetime.now(UTC)
        self.reminder_sent_at = moment
        self.updated_at = moment

    @property
    def is_terminal(self) -> bool:
        return self.status in TERMINAL_STATUSES

    @property
    def occupies_slot(self) -> bool:
        """False once the appointment has released its time back to the calendar."""
        return self.status not in RELEASING_STATUSES

    def validation_error(self) -> str | None:
        if not self.customer_name.strip():
            return "A customer name is required."
        if not (self.customer_phone.strip() or self.customer_email.strip()):
            # Without one of these there is no way to send a confirmation or a
            # reminder, which makes the appointment unactionable.
            return "A phone number or an email address is required."
        if self.ends_at <= self.starts_at:
            return "An appointment must end after it starts."
        if self.status not in ALL_STATUSES:
            return f"{self.status!r} isn't a valid appointment status."
        if self.source not in ALL_SOURCES:
            return f"{self.source!r} isn't a valid booking source."
        if self.timezone and not is_valid_timezone(self.timezone):
            return f"{self.timezone!r} isn't a recognised IANA timezone."
        return None

    def normalized(self) -> Appointment:
        self.customer_name = self.customer_name.strip()[:MAX_NAME]
        self.customer_phone = self.customer_phone.strip()[:32]
        self.customer_email = self.customer_email.strip()[:320]
        self.customer_notes = self.customer_notes.strip()[:MAX_NOTES]
        self.internal_notes = self.internal_notes.strip()[:MAX_NOTES]
        return self

    def transition_to(
        self,
        target: AppointmentStatus,
        *,
        actor_kind: ActorKind,
        actor_id: uuid.UUID | None = None,
        actor_label: str = "",
        channel: str = "",
        reason: str = "",
    ) -> StatusChange:
        """Move to `target`, returning the history row the caller must persist.

        Raises rather than returning a flag: an unrecorded illegal transition is
        how an appointment ends up "completed" after being cancelled, and the
        history is the only account of what happened.
        """
        if target == self.status:
            raise InvalidStateError(
                f"This appointment is already {target.replace('_', ' ')}."
            )
        if not can_transition(self.status, target):
            raise InvalidStateError(
                f"An appointment that is {self.status.replace('_', ' ')} "
                f"cannot become {target.replace('_', ' ')}."
            )
        change = StatusChange(
            appointment_id=self.id,
            tenant_id=self.tenant_id,
            from_status=self.status,
            to_status=target,
            actor_kind=actor_kind,
            actor_id=actor_id,
            actor_label=actor_label,
            channel=channel,
            reason=reason,
        )
        self.status = target
        if target == "cancelled" and reason:
            self.cancellation_reason = reason[:500]
        self.updated_at = datetime.now(UTC)
        return change


@dataclass
class SlotHold:
    """A short-lived claim on a slot while a customer finishes booking (section 12).

    Exists because the gap between "I'll take 3pm" and a completed booking is
    long enough for someone else to take it — on a voice call, minutes. The hold
    is enforced by the same database constraint as a real booking, so a held
    slot is genuinely unbookable rather than merely marked.
    """

    tenant_id: TenantId
    service_id: ServiceId
    location_id: LocationId
    starts_at: datetime
    ends_at: datetime
    resource_ids: list[ResourceId]
    expires_at: datetime
    id: uuid.UUID = field(default_factory=new_id)
    token: str = ""
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def is_expired(self, now: datetime | None = None) -> bool:
        return (now or datetime.now(UTC)) >= self.expires_at


# How long a hold survives without being converted. Long enough for a phone
# conversation, short enough that an abandoned booking frees the slot while the
# customer is still on the page.
DEFAULT_HOLD_TTL = timedelta(minutes=10)
