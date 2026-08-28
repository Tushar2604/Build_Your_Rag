# Testing the appointment engine

## What runs where

| File | Count | Needs a database? |
|---|---|---|
| `tests/domain/test_availability_engine.py` | 25 | No |
| `tests/domain/test_appointment_lifecycle.py` | 30 | No |
| `tests/test_scheduling_schema_parity.py` | 50 | No |
| `tests/test_scheduling_agent_tools.py` | 20 | No |
| `tests/test_event_serialization.py` | 10 | No |
| `tests/test_slot_hold_concurrency.py` | 11 | **Yes — Postgres** |

The first five run in CI with no infrastructure, matching this repository's
existing hermetic convention (there is no `conftest.py` and no test database).

## The one that needs a real database

`tests/test_slot_hold_concurrency.py` **skips loudly** unless
`TEST_DATABASE_URL` is set:

```bash
docker run -d --name rag_test -e POSTGRES_USER=rag -e POSTGRES_PASSWORD=rag \
  -e POSTGRES_DB=rag -p 55432:5432 pgvector/pgvector:pg16

TEST_DATABASE_URL=postgresql+asyncpg://rag:rag@localhost:55432/rag \
  pytest tests/test_slot_hold_concurrency.py -v
```

It cannot be faked. The guarantee is a GiST exclusion constraint; SQLite has no
exclusion constraints, no `tstzrange`, and no `btree_gist`, so a fake would
assert only that the fake is consistent. A silently-absent concurrency test is
how a scheduler ships able to double-book.

It verifies:

- 2 and 10 clients racing for one slot produce **exactly one** reservation
- a hold and a booking compete for the same time
- partial overlaps conflict; back-to-back appointments do **not**
- a busy resource never blocks a free one
- releasing a reservation frees the slot, repeatedly
- an expired hold still blocks until released — and why the booking path
  releases it inline rather than waiting for the sweep

**This test found a real bug.** The first version of `reserve` caught only
`IntegrityError`, so it handled `23P01 exclusion_violation` but not
`40P01 deadlock_detected` — which is what Postgres actually raises when two
racers are genuinely simultaneous. Exactly one booking still won, but the loser
got a 500 instead of "that time was just taken". `TestTheConflictClassifier`
is the regression guard.

## The hermetic suites

**Availability engine** — the engine is pure, so these are fabricated inputs and
assertions with no clock dependency (`now` is passed in). Covers buffers,
minimum notice, horizon, blocks, multi-resource intersection, preferred
resources, and both daylight-saving transitions in `Europe/London`.

**Lifecycle** — every legal transition and every illegal one, that terminal
statuses are genuinely terminal, that a rejected transition leaves the status
untouched, and that cancelling releases the slot while completing does not.

**Schema parity** — renders migration 0025's DDL offline and diffs it against the
ORM, then pins the exclusion constraint, the partial idempotency index, RLS on
all nine tables, the `ON DELETE` choices, the performance indexes, and the
rollback order.

**Agent tools** — an in-memory unit of work, verifying that the tools return only
engine-computed times, that a time the engine never offered is refused, that
losing a race tells the agent what to do next, and that another tenant's ids are
invisible.

**Event serialization** — regression guards for a datetime field breaking the
audit write, and for that failure taking down a booking that had already
committed.

## End-to-end

`docs/appointments/` has no fixture for this; the walkthrough is manual and lives
in the plan's verification section. Against a live API and a real Postgres it
covers 39 checks: configuration, cross-tenant rejection, availability including
the Dubai 09:00 → 05:00Z conversion, booking, idempotent replay, double-booking
409, buffer effects, an invented time being refused, the full lifecycle, an
illegal transition, history, holds, hold conversion, reschedule, cancel, and slot
release.

## Running everything

```bash
# Hermetic — what CI runs
pytest -q

# Plus the concurrency proof
TEST_DATABASE_URL=postgresql+asyncpg://rag:rag@localhost:55432/rag pytest -q

# Static
ruff check src tests
mypy src
```
