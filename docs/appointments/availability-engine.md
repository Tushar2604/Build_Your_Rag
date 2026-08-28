# The availability engine

`src/domain/scheduling/availability.py` — the one place that decides when
something is bookable.

## The contract

```python
compute_slots(request, inputs, *, now) -> list[Slot]
```

A slot in the returned list has passed **all** of:

- the service's minimum notice and booking horizon
- the branch's opening hours for that local day
- each required resource's own hours, intersected with the branch's
- every blocked period on the branch and on each resource
- every existing booking and every live hold, widened by the service's buffers
- a concrete resource assigned to each required role

A caller may present these to a customer without re-checking anything. That is
the whole point: the browser has no availability logic, and neither does the
agent.

## Inputs

Gathered by `load_availability_inputs` in four queries regardless of how many
resources are involved — one per resource would make a ten-staff search eleven
round trips before any work happens.

| Input | Source |
|---|---|
| `service` | `services` |
| `candidates_by_role` | `service_resources` joined to `resources`, grouped by role |
| `rules_by_owner` | `availability_rules` for the branch and every candidate |
| `blocks_by_owner` | `blocked_periods` overlapping the window |
| `busy_by_resource` | live `resource_reservations` — bookings **and** holds |

Holds are counted as busy deliberately: a slot someone is midway through booking
must not be offered to the next caller.

## How a slot is built

1. Clamp the requested window to `[now + min_notice, now + max_horizon]`, then
   to `MAX_QUERY_DAYS` (62), so one request cannot materialise a year.
2. Resolve the branch's weekly rules into UTC intervals for each **local**
   calendar day the window touches, and merge overlaps.
3. For each resource, intersect its own rules with the branch's. A resource with
   no rules inherits the branch's — the common setup, where only exceptions are
   configured per person.
4. Walk a grid (default 15 minutes) anchored to each opening window's start, so
   a branch opening at 09:00 offers 09:00 and not 09:07.
5. At each point, build the **reservation block** = appointment ± buffers, and
   ask each role for a free candidate.
6. Emit a slot only when every required role is filled.

The appointment and the reservation block are different spans, and that
distinction is what makes buffers work: a 30-minute consultation with a
10-minute cleanup blocks 40 minutes of calendar but shows the customer a
30-minute appointment.

`reservation_window(service, starts_at)` computes that block, and is used by both
the availability path and the booking path. One function, or a slot the engine
offered could be rejected on save.

## Intervals are half-open

`[start, end)`. An appointment ending at 3:00 PM and one starting at 3:00 PM do
not conflict — in the domain's `Interval.overlaps`, and in the database's
`tstzrange(starts_at, ends_at, '[)')`. A closed range would make every
back-to-back booking a conflict and halve a clinic's capacity.

## Daylight saving

Weekly rules are wall-clock. `datetime.combine(day, local_time, tzinfo=zone)` is
where DST is handled — `zoneinfo` resolves the time against that day's actual
offset.

A worked example from the test suite (`Europe/London`, 2026):

| Date | Rule | Resolved UTC | Local |
|---|---|---|---|
| Mon 23 Mar (GMT) | 09:00 | `09:00Z` | 09:00 |
| Mon 30 Mar (BST) | 09:00 | `08:00Z` | 09:00 |

The UTC instants genuinely differ, because both are 09:00 to someone standing in
London. Storing the instant instead would have moved the branch's opening time.

A fall-back day (25 Oct, when 01:00–02:00 happens twice) is also covered: the
grid still produces strictly increasing, unique start times rather than two
01:30 slots.

## Concurrency

This is the part that cannot be done in application code.

Checking availability and then inserting always leaves a window between the two,
and `SELECT ... FOR UPDATE` cannot lock a row that does not exist yet.
Serializing every booking through one lock would be correct and unusably slow.

So the guarantee lives in Postgres. Holds and bookings are rows in **one** table,
`resource_reservations`, with:

```sql
EXCLUDE USING gist (
    resource_id WITH =,
    (tstzrange(starts_at, ends_at, '[)')) WITH &&
) WHERE (released_at IS NULL)
```

Whoever commits second loses. No lock ordering, no retry loop, no dependence on
worker count. `btree_gist` is required because the constraint mixes btree
equality on a `uuid` with a GiST range overlap in one index.

### Losing a race has two shapes

Verified against a real Postgres, and the reason
`tests/test_slot_hold_concurrency.py` exists:

| SQLSTATE | When | 
|---|---|
| `23P01` exclusion_violation | The other booking had already committed. |
| `40P01` deadlock_detected | The two were genuinely simultaneous. Checking the constraint takes a `ShareLock` on the conflicting transaction to see whether it commits; when each racer holds a row the other waits on, Postgres breaks the tie by killing one. |
| `40001` serialization_failure | The same situation under stricter isolation. Included so raising the isolation level later cannot reintroduce the bug. |

All three mean the same thing to a customer, and `_is_slot_conflict` maps them to
a 409. **The first version of this code caught only `IntegrityError`**, so a
genuinely simultaneous booking surfaced as a 500 — a bug no hermetic test could
have found.

### Expired holds

The constraint's predicate must be immutable, so it cannot read the clock: an
expired-but-unreleased hold still blocks at the database level. Two things
follow, both deliberate:

- The booking path calls `purge_expired_holds` on the resources it is about to
  claim, **inside its own transaction**, so correctness never waits for a
  background sweep.
- The availability query also filters on `expires_at`, so a slot is never
  withheld merely because housekeeping has not run.

`ExpireSlotHolds` (the app's sweep loop) is tidying only. It takes no advisory
lock and needs none — releasing an already-expired hold is idempotent.

### Rescheduling

Release the old reservation, then claim the new one, in one transaction. Order
matters: moving an appointment fifteen minutes later reuses the same resource, so
claiming first would make it collide with itself. Releasing first is safe
precisely because it is the same transaction — if the new claim loses a race,
everything rolls back and the original booking stands.

## Performance

- Bounded date-range queries against indexed columns. No precomputation.
- **No availability cache.** A stale cache would permit real double bookings,
  and the constraint would then reject the booking after the customer was told
  they had it.
- The busy-time lookup uses a partial index on live reservations; released rows
  are the majority over time and are never read by the availability path.
