# Appointment architecture

## Where things live

The module follows the repository's existing layering exactly — nothing new was
introduced, and no existing infrastructure was replaced.

```
src/domain/scheduling/
  entities.py       Location, Service, Resource, Appointment, SlotHold,
                    AvailabilityRule, BlockedPeriod, the status transition table
  availability.py   THE ENGINE. A pure function. No I/O, no session, no clock.
  events.py         AppointmentCreated / StatusChanged / Rescheduled

src/application/
  ports/repositories.py     Six new Protocols + the HeldReservation DTO
  use_cases/availability.py FindAvailability, HoldSlot, ReleaseSlotHold
  use_cases/appointments.py BookAppointment, TransitionAppointment,
                            RescheduleAppointment, UpdateAppointmentDetails,
                            ExpireSlotHolds

src/infrastructure/
  persistence/models.py                   9 ORM models
  persistence/scheduling_repositories.py  Repositories + mappers + the
                                          conflict classifier
  agent/scheduling_tools.py               list_services, find_available_slots,
                                          create_slot_hold

src/interfaces/api/routers/
  locations.py services.py resources.py availability.py appointments.py

frontend/src/
  api/appointments.ts
  pages/AppointmentsCalendarPage AppointmentsPage ServicesPage
        ResourcesPage LocationsPage AvailabilityPage
  components/BookAppointmentModal AppointmentDrawer

migrations/versions/0025_scheduling_foundation.py
```

## Why the engine is a pure function

`domain/scheduling/availability.py` takes already-fetched inputs and returns
slots. It opens no session and reads no clock (`now` is a parameter).

Three reasons, in order of importance:

1. **It is the part that is actually hard.** Buffers, multi-resource
   intersection, minimum notice, and daylight saving all interact. The only way
   to test that exhaustively is to call it with fabricated inputs — 25 cases in
   `tests/domain/test_availability_engine.py`, including both DST transitions,
   none of which need a database.
2. **Every channel must get the same answer.** One function, called by one use
   case, guarantees it. A second implementation for the widget or the voice
   agent is how two channels start disagreeing about whether 3pm is free.
3. **It is authoritative.** Slots the AI offers come from here. The model is
   never in a position to invent one.

The use case's job is to gather inputs (four queries, not N) and hand them over.
It contains no scheduling arithmetic.

## Timezones

Scheduling software fails on timezones, so the rule is explicit:

- **Every instant is `timestamptz`, UTC.** Appointments, blocks, reservations.
- **Availability rules are the sole exception**: they store a weekday and local
  wall-clock `TIME`, because "open Mondays 09:00" must stay 09:00 through a
  daylight-saving change. A stored UTC offset would move every branch by an hour
  twice a year.
- The two are reconciled in `_windows_for`, using `zoneinfo`. On a
  spring-forward day a 02:30 rule resolves to the post-jump instant; on a
  fall-back day, the first of the two 01:30s. Both are stable, and neither
  requires the module to know a transition happened.
- **No critical logic runs on formatted strings.** The frontend renders with
  `Intl.DateTimeFormat` against the branch's zone and never does date
  arithmetic on the result.
- An appointment copies its branch's timezone at booking time, so correcting a
  branch's zone later cannot retroactively move appointments that already
  happened.

`tzdata` is a hard dependency: `zoneinfo` reads the system database on Linux and
macOS, but Windows ships none, so a developer machine raises
`ZoneInfoNotFoundError` on every availability query without it.

## Events

The three appointment events are collected on the unit of work and dispatched
after commit, exactly like the existing chat and document events. Two things
follow for free from the current in-process bus:

- Every event is persisted to `audit_events`, which is the substrate of the
  audit trail.
- Later phases (reminders, webhooks, calendar sync, analytics) subscribe here
  rather than being wired into the booking use case.

Publishing is guarded: events dispatch *after* the business transaction commits,
so an audit write that raised would turn a booking that genuinely succeeded into
a 500 the caller retries. That is now caught and logged.

## Tenant isolation

Unchanged from the rest of the platform, and applied to all nine tables:

- Every repository query filters `tenant_id` explicitly (primary guard).
- Postgres RLS policies keyed on `app.tenant_id` (backstop).
- Another tenant's id reads as **404, not 403** — a 403 would confirm the row
  exists.
- Polymorphic owners (`availability_rules.owner_id`, `blocked_periods.owner_id`)
  carry no foreign key, so the routers check ownership explicitly before
  writing. Without that, a crafted body could attach opening hours to another
  tenant's branch.

## Deliberately deferred

Naming these matters as much as what was built.

| Not built | Why |
|---|---|
| Customer/CRM entity | Appointments carry customer fields directly. The columns are named to match the entity that will replace them, so the later change is a backfill rather than a redesign. |
| Google Calendar sync | The existing client writes one way only. A half-sync that lets external events cause double bookings is worse than none. Phase 6. |
| `book_appointment` agent tool | Booking on a customer's behalf needs the identity and consent context a channel supplies. It arrives with the channel that uses it. |
| Granular RBAC | Config surfaces use the existing `AdminPrincipalDep`; read and booking use `PrincipalDep`. Per-permission RBAC is Phase 8. |
| Resource capacity > 1 | The column exists and the engine reads it, but the database guard is written for capacity 1. Group bookings need a different constraint shape. |
| Optional (`required=False`) eligibility roles | Stored, but ignored by the engine: requiring an optional resource to be free would be stricter than the configuration asks for. |
| Interview migration | `interviews` and `interview_batches` are untouched. Folding them in is a decision to make deliberately, not a side effect of adding a scheduler. |
