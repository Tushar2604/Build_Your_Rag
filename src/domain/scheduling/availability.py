"""The availability engine — the one place that decides when something is bookable.

Deliberately a pure function over already-fetched inputs. It opens no session,
makes no query, and calls nothing external, for three reasons:

  * It is the part of a scheduler that is actually hard, and the only way to
    test it exhaustively (daylight saving, buffers, multi-resource conflicts) is
    to be able to call it with fabricated inputs and no database.
  * Every channel — dashboard, WhatsApp, voice, widget, public API — must get
    identical answers. One function, called by one use case, guarantees that.
  * It is authoritative (spec section 11 and section 61). Slots the AI offers
    come from here; the model is never in a position to invent one.

Timezone handling is the load-bearing detail. Availability *rules* are local
wall-clock ("Mondays 09:00-17:00"); everything else is a UTC instant. This module
converts the former into the latter per calendar day, using `zoneinfo`, so an
hour that does not exist (spring forward) or happens twice (fall back) is
resolved by the tz database rather than by arithmetic on an offset.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from src.domain.scheduling.entities import (
    AvailabilityRule,
    BlockedPeriod,
    Resource,
    Service,
)
from src.domain.shared.identifiers import LocationId, ResourceId, ServiceId

# How finely slot start times are offered. Fifteen minutes is the granularity
# real front desks think in; a service whose duration is not a multiple of it
# still gets offered (the grid is start times, not durations).
DEFAULT_SLOT_GRANULARITY_MINUTES = 15

# Ceiling on the window a single query may span, so one request cannot ask the
# engine to materialise a year of slots.
MAX_QUERY_DAYS = 62


@dataclass(frozen=True)
class Interval:
    """A half-open UTC interval [start, end). Half-open is what makes an
    appointment ending at 3pm and one starting at 3pm not a conflict."""

    start: datetime
    end: datetime

    def overlaps(self, other: Interval) -> bool:
        return self.start < other.end and other.start < self.end

    def contains(self, other: Interval) -> bool:
        return self.start <= other.start and other.end <= self.end


@dataclass(frozen=True)
class Slot:
    """One bookable start time, with the exact resources that would serve it.

    `resource_ids` is not advisory: booking this slot reserves precisely these
    resources. Returning them is what lets the booking call be a confirmation of
    an earlier decision rather than a second, racing search.
    """

    starts_at: datetime
    ends_at: datetime
    resource_ids: tuple[ResourceId, ...]

    @property
    def interval(self) -> Interval:
        return Interval(self.starts_at, self.ends_at)


@dataclass
class AvailabilityRequest:
    """Everything the caller is asking for. Times are UTC instants."""

    tenant_id: object
    location_id: LocationId
    service_id: ServiceId
    range_start: datetime
    range_end: datetime
    # The zone the *location* operates in, used to resolve weekly rules into
    # instants. Not the customer's zone — that only affects display.
    location_timezone: str = "UTC"
    # Restrict to one named resource ("I want Dr Khan"). Others still fill the
    # remaining required roles.
    preferred_resource_id: ResourceId | None = None
    granularity_minutes: int = DEFAULT_SLOT_GRANULARITY_MINUTES
    # Caps the response so a wide range cannot produce an unbounded payload.
    limit: int = 200


@dataclass
class AvailabilityInputs:
    """The world as the repositories found it, already tenant-scoped.

    Passing this as one object rather than eight arguments keeps the engine's
    signature stable as later phases add inputs (capacity overrides, external
    calendar busy-time from section 35).
    """

    service: Service
    # Candidate resources grouped by the role they fill. A role with no
    # candidates makes the whole service unbookable, which is correct: a
    # consultation with no room is not a consultation.
    candidates_by_role: dict[str, list[Resource]]
    # Rules for the location and for every candidate resource, keyed by owner id.
    rules_by_owner: dict[object, list[AvailabilityRule]]
    # Blocked periods (leave, holidays, maintenance) keyed by owner id.
    blocks_by_owner: dict[object, list[BlockedPeriod]]
    # Time already taken — confirmed appointments AND live slot holds — keyed by
    # resource id. Holds are included deliberately: a slot someone is midway
    # through booking must not be offered to the next caller.
    busy_by_resource: dict[ResourceId, list[Interval]] = field(default_factory=dict)


def _as_utc(value: datetime) -> datetime:
    """Normalise to an aware UTC datetime.

    A naive datetime reaching the engine is a bug upstream, but treating it as
    UTC is safer than raising here: the alternative is a 500 on an availability
    query, and every persisted timestamp in this system is already UTC.
    """
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _local_days(start: datetime, end: datetime, tz: ZoneInfo) -> list[date]:
    """Every local calendar day the UTC window touches.

    Iterating local days rather than UTC days is what makes "Mondays 09:00" mean
    Monday at the branch. A UTC window can straddle three local days at either
    end of the world, so both edges are included.
    """
    first = start.astimezone(tz).date()
    last = end.astimezone(tz).date()
    days: list[date] = []
    cursor = first
    while cursor <= last:
        days.append(cursor)
        cursor += timedelta(days=1)
    return days


def _rule_applies_on(rule: AvailabilityRule, day: date, tz: ZoneInfo) -> bool:
    if not rule.is_active or rule.weekday != day.weekday():
        return False
    # An effective window is an absolute range, compared against the start of
    # the local day so a rule that begins mid-day still applies to that day.
    day_start = datetime.combine(day, time.min, tzinfo=tz).astimezone(UTC)
    if rule.effective_from and day_start < _as_utc(rule.effective_from):
        return False
    return not (rule.effective_until and day_start >= _as_utc(rule.effective_until))


def _windows_for(
    rules: list[AvailabilityRule], days: list[date], tz: ZoneInfo
) -> list[Interval]:
    """Turn weekly wall-clock rules into concrete UTC intervals.

    `datetime.combine(day, local_time, tzinfo=tz)` is where daylight saving is
    handled: zoneinfo resolves the wall-clock time against that day's actual
    offset. On a spring-forward day a 02:30 rule lands on the post-jump instant
    rather than a time that never existed; on a fall-back day the first of the
    two 01:30s is used. Both are stable, documented choices — and neither
    requires this module to know a transition happened.
    """
    windows: list[Interval] = []
    for day in days:
        for rule in rules:
            if not _rule_applies_on(rule, day, tz):
                continue
            start = datetime.combine(day, rule.start_time, tzinfo=tz).astimezone(UTC)
            end = datetime.combine(day, rule.end_time, tzinfo=tz).astimezone(UTC)
            if end > start:
                windows.append(Interval(start, end))
    return _merge(windows)


def _merge(intervals: list[Interval]) -> list[Interval]:
    """Union overlapping/adjacent intervals. Two rules covering 09:00-13:00 and
    12:00-17:00 are one 09:00-17:00 window, not two with a double-counted hour."""
    if not intervals:
        return []
    ordered = sorted(intervals, key=lambda i: i.start)
    merged = [ordered[0]]
    for current in ordered[1:]:
        last = merged[-1]
        if current.start <= last.end:
            merged[-1] = Interval(last.start, max(last.end, current.end))
        else:
            merged.append(current)
    return merged


def _intersect(left: list[Interval], right: list[Interval]) -> list[Interval]:
    """Time present in both lists. Used to fold a resource's own schedule into
    the branch's opening hours: a doctor rostered 08:00-18:00 at a branch open
    09:00-17:00 is available 09:00-17:00."""
    out: list[Interval] = []
    i = j = 0
    while i < len(left) and j < len(right):
        start = max(left[i].start, right[j].start)
        end = min(left[i].end, right[j].end)
        if start < end:
            out.append(Interval(start, end))
        if left[i].end <= right[j].end:
            i += 1
        else:
            j += 1
    return out


def _blocks_to_intervals(blocks: list[BlockedPeriod]) -> list[Interval]:
    return _merge(
        [Interval(_as_utc(b.starts_at), _as_utc(b.ends_at)) for b in blocks]
    )


def _resource_free(
    resource: Resource,
    block: Interval,
    inputs: AvailabilityInputs,
    open_windows: list[Interval],
) -> bool:
    """Can this one resource take `block` (the slot plus its buffers)?"""
    if not resource.is_active:
        return False
    # Must sit entirely inside a window where both the branch and the resource
    # are open. `open_windows` is already that intersection.
    if not any(window.contains(block) for window in open_windows):
        return False
    for blocked in _blocks_to_intervals(inputs.blocks_by_owner.get(resource.id, [])):
        if blocked.overlaps(block):
            return False
    return all(
        not busy.overlaps(block)
        for busy in inputs.busy_by_resource.get(resource.id, [])
    )


def _pick_resources(
    block: Interval,
    inputs: AvailabilityInputs,
    windows_by_resource: dict[ResourceId, list[Interval]],
    preferred: ResourceId | None,
) -> tuple[ResourceId, ...] | None:
    """One free resource per required role, or None if any role cannot be filled.

    A greedy pick per role is correct here because roles draw from disjoint sets
    in every configuration the product supports — a room is not also a
    practitioner. Were that to change, this is the single place a matching
    algorithm would go.
    """
    chosen: list[ResourceId] = []
    for _role, candidates in sorted(inputs.candidates_by_role.items()):
        if not candidates:
            return None
        # A named preference is honoured within whichever role that resource
        # fills, and ignored for the others.
        ordered = candidates
        if preferred is not None and any(c.id == preferred for c in candidates):
            ordered = [c for c in candidates if c.id == preferred]
        pick = next(
            (
                c.id
                for c in ordered
                if c.id not in chosen
                and _resource_free(c, block, inputs, windows_by_resource.get(c.id, []))
            ),
            None,
        )
        if pick is None:
            return None
        chosen.append(pick)
    return tuple(chosen)


def compute_slots(
    request: AvailabilityRequest,
    inputs: AvailabilityInputs,
    *,
    now: datetime,
) -> list[Slot]:
    """Every genuinely bookable start time in the requested window.

    "Genuinely" is the whole contract: a slot in this list has passed the
    service's notice and horizon rules, sits inside both the branch's and each
    resource's working hours, avoids every block and every existing booking or
    hold, and has a concrete resource assigned to each required role. A caller
    may present these to a customer without re-checking anything.

    The slot returned covers the *appointment*, while conflicts are checked
    against the appointment plus its buffers. That distinction is why buffers
    work: a 30-minute consultation with a 10-minute cleanup blocks 40 minutes of
    calendar but shows the customer a 30-minute appointment.
    """
    service = inputs.service
    if not service.is_active:
        return []

    now = _as_utc(now)
    tz = ZoneInfo(request.location_timezone or "UTC")

    # --- Clamp the window to what the service actually permits (section 11) ---
    earliest = max(
        _as_utc(request.range_start), now + timedelta(minutes=service.min_notice_minutes)
    )
    horizon = now + timedelta(days=service.max_horizon_days)
    latest = min(_as_utc(request.range_end), horizon)
    # Independently of the service's horizon, refuse to materialise more than
    # MAX_QUERY_DAYS at once.
    latest = min(latest, earliest + timedelta(days=MAX_QUERY_DAYS))
    if latest <= earliest:
        return []

    days = _local_days(earliest, latest, tz)

    location_windows = _windows_for(
        inputs.rules_by_owner.get(request.location_id, []), days, tz
    )
    if not location_windows:
        # A branch with no hours is closed. Returning nothing is the honest
        # answer; the alternative (assume 24/7) books appointments at 3am.
        return []
    location_blocks = _blocks_to_intervals(
        inputs.blocks_by_owner.get(request.location_id, [])
    )

    # Each resource's own hours, already folded into the branch's. A resource
    # with no rules of its own inherits the branch's hours — the common setup,
    # where only exceptions are configured per person.
    windows_by_resource: dict[ResourceId, list[Interval]] = {}
    for candidates in inputs.candidates_by_role.values():
        for resource in candidates:
            own = inputs.rules_by_owner.get(resource.id, [])
            resource_tz = ZoneInfo(resource.timezone) if resource.timezone else tz
            windows = (
                _intersect(location_windows, _windows_for(own, days, resource_tz))
                if own
                else location_windows
            )
            windows_by_resource[resource.id] = windows

    step = timedelta(minutes=max(1, request.granularity_minutes))
    duration = timedelta(minutes=service.duration_minutes)
    lead = timedelta(minutes=service.buffer_before_minutes)
    trail = timedelta(minutes=service.buffer_after_minutes)

    slots: list[Slot] = []
    for window in location_windows:
        # Start the grid on a granularity boundary measured from the window's
        # own start, so a branch opening at 09:00 offers 09:00 and not 09:07.
        cursor = max(window.start, earliest)
        offset = (cursor - window.start) % step
        if offset:
            cursor += step - offset

        while cursor + duration <= min(window.end, latest):
            appointment = Interval(cursor, cursor + duration)
            # Buffers extend the reservation, not the appointment.
            block = Interval(appointment.start - lead, appointment.end + trail)

            if any(b.overlaps(block) for b in location_blocks):
                cursor += step
                continue

            picked = _pick_resources(
                block, inputs, windows_by_resource, request.preferred_resource_id
            )
            if picked is not None:
                slots.append(
                    Slot(
                        starts_at=appointment.start,
                        ends_at=appointment.end,
                        resource_ids=picked,
                    )
                )
                if len(slots) >= request.limit:
                    return slots
            cursor += step

    return slots


def reservation_window(service: Service, starts_at: datetime) -> Interval:
    """The interval a booking of `service` at `starts_at` actually reserves.

    Buffers included — this is what goes into the database's overlap constraint,
    and it must be computed identically by the availability path and the booking
    path or a slot the engine offered could be rejected on save. One function,
    used by both, is what keeps them honest.
    """
    start = _as_utc(starts_at)
    return Interval(
        start - timedelta(minutes=service.buffer_before_minutes),
        start
        + timedelta(minutes=service.duration_minutes + service.buffer_after_minutes),
    )
