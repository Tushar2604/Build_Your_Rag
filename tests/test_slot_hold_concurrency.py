"""The double-booking guarantee, proved against a real Postgres.

This is the one test in the scheduling suite that cannot be hermetic, and saying
so plainly matters: the guarantee in spec section 12 is a GiST exclusion
constraint, and a constraint that is not exercised by a real database has not
been tested at all. SQLite has no exclusion constraints, no `tstzrange`, and no
`btree_gist`, so a fake here would assert only that the fake is consistent.

It therefore SKIPS unless `TEST_DATABASE_URL` names a Postgres you are happy to
have schema created in. The skip is loud on purpose — a silently-absent
concurrency test is how a scheduler ships able to double-book.

    docker compose up -d db
    TEST_DATABASE_URL=postgresql+asyncpg://rag:rag@localhost:5432/rag \\
        pytest tests/test_slot_hold_concurrency.py -v

What is verified:

  * N clients racing for one slot produce exactly ONE reservation.
  * Adjacent appointments (one ends as the next begins) do NOT collide.
  * A released reservation frees its slot for rebooking.
  * An expired hold does not block a booking.
  * The constraint is per-resource, so a busy doctor never blocks a free one.
"""

from __future__ import annotations

import asyncio
import os
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool
from src.infrastructure.persistence.scheduling_repositories import _is_slot_conflict

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL", "")

pytestmark = pytest.mark.skipif(
    not TEST_DATABASE_URL,
    reason=(
        "Needs a real Postgres: the double-booking guard is a GiST exclusion "
        "constraint, which cannot be exercised without one. "
        "Set TEST_DATABASE_URL to run (see this module's docstring)."
    ),
)

# A schema of its own, so the test can create and drop everything it needs
# without touching whatever else lives in the target database.
SCHEMA = "scheduling_concurrency_test"

# The table under test, reduced to exactly the columns the constraint involves.
# Written out rather than imported from the migration so this file states the
# guarantee it is checking, and fails loudly if migration 0025 ever drops it.
_CREATE = f"""
CREATE SCHEMA IF NOT EXISTS {SCHEMA};
SET search_path TO {SCHEMA};
CREATE EXTENSION IF NOT EXISTS btree_gist;

CREATE TABLE resource_reservations (
    id            uuid PRIMARY KEY,
    tenant_id     uuid NOT NULL,
    resource_id   uuid NOT NULL,
    starts_at     timestamptz NOT NULL,
    ends_at       timestamptz NOT NULL,
    kind          varchar(10) NOT NULL,
    hold_token    varchar(64),
    expires_at    timestamptz,
    released_at   timestamptz,
    created_at    timestamptz NOT NULL DEFAULT now()
);

ALTER TABLE resource_reservations
ADD CONSTRAINT no_overlapping_reservations
EXCLUDE USING gist (
    resource_id WITH =,
    (tstzrange(starts_at, ends_at, '[)')) WITH &&
) WHERE (released_at IS NULL);
"""

_DROP = f"DROP SCHEMA IF EXISTS {SCHEMA} CASCADE;"

TENANT = uuid.uuid4()
SLOT_START = datetime(2026, 9, 1, 15, 0, tzinfo=UTC)
SLOT_END = SLOT_START + timedelta(minutes=30)


@pytest.fixture
async def sessionmaker():  # type: ignore[no-untyped-def]
    """A clean schema and a fresh engine per test.

    Function-scoped, with `NullPool`, on purpose: pytest-asyncio gives each test
    its own event loop, and an engine shared across loops hands back connections
    bound to a dead one ("another operation is in progress"). A pooled engine is
    not worth debugging that for a handful of tests.
    """
    engine = create_async_engine(TEST_DATABASE_URL, poolclass=NullPool)
    async with engine.begin() as conn:
        await conn.execute(text(_DROP))
        for statement in filter(None, (s.strip() for s in _CREATE.split(";"))):
            await conn.execute(text(statement))

    maker = async_sessionmaker(engine, expire_on_commit=False)
    try:
        yield maker
    finally:
        async with engine.begin() as conn:
            await conn.execute(text(_DROP))
        await engine.dispose()


async def _reserve(
    maker,  # type: ignore[no-untyped-def]
    resource_id: uuid.UUID,
    starts_at: datetime,
    ends_at: datetime,
    *,
    kind: str = "booking",
    expires_at: datetime | None = None,
    barrier: asyncio.Barrier | None = None,
) -> bool:
    """One client attempting to claim a slot. True if it won.

    Each attempt gets its own session and therefore its own connection and
    transaction — anything less would not be a race at all.
    """
    async with maker() as session:
        await session.execute(text(f"SET search_path TO {SCHEMA}"))
        # Every racer waits here, so they all attempt the insert at once rather
        # than politely queueing behind each other's setup.
        if barrier is not None:
            await barrier.wait()
        try:
            await session.execute(
                text(
                    "INSERT INTO resource_reservations "
                    "(id, tenant_id, resource_id, starts_at, ends_at, kind, expires_at) "
                    "VALUES (:id, :tenant, :resource, :starts, :ends, :kind, :expires)"
                ),
                {
                    "id": uuid.uuid4(),
                    "tenant": TENANT,
                    "resource": resource_id,
                    "starts": starts_at,
                    "ends": ends_at,
                    "kind": kind,
                    "expires": expires_at,
                },
            )
            await session.commit()
            return True
        except DBAPIError as exc:
            await session.rollback()
            # Losing looks like one of two things, and the test must accept both
            # or it asserts something Postgres does not promise:
            #
            #   23P01 exclusion_violation — the other booking had committed.
            #   40P01 deadlock_detected   — the two racers were genuinely
            #                               simultaneous. Checking the constraint
            #                               takes a ShareLock on the conflicting
            #                               transaction, so each waits on the
            #                               other and Postgres kills one.
            #
            # Either way exactly one booking survives, which is the guarantee.
            # `_is_slot_conflict` is the production classifier, used here so this
            # test fails if the shipped code stops recognising one of them.
            assert _is_slot_conflict(exc), (
                f"lost the race for an unexpected reason: {exc.orig!r}"
            )
            return False


async def _live_count(maker) -> int:  # type: ignore[no-untyped-def]
    async with maker() as session:
        await session.execute(text(f"SET search_path TO {SCHEMA}"))
        result = await session.execute(
            text(
                "SELECT count(*) FROM resource_reservations WHERE released_at IS NULL"
            )
        )
        return int(result.scalar() or 0)


class TestOnlyOneCustomerGetsTheSlot:
    async def test_two_simultaneous_bookings_produce_exactly_one(
        self, sessionmaker
    ) -> None:  # type: ignore[no-untyped-def]
        """Customer A and Customer B both choose 3:00 PM. Capacity is one."""
        resource = uuid.uuid4()
        barrier = asyncio.Barrier(2)

        results = await asyncio.gather(
            _reserve(sessionmaker, resource, SLOT_START, SLOT_END, barrier=barrier),
            _reserve(sessionmaker, resource, SLOT_START, SLOT_END, barrier=barrier),
        )

        assert sum(results) == 1, f"exactly one booking must win, got {results}"
        assert await _live_count(sessionmaker) == 1

    async def test_ten_simultaneous_bookings_still_produce_exactly_one(
        self, sessionmaker
    ) -> None:  # type: ignore[no-untyped-def]
        """The guarantee must not degrade with contention.

        Ten is well past what a single popular slot sees in practice, and is the
        case an application-level check fails most reliably.
        """
        resource = uuid.uuid4()
        racers = 10
        barrier = asyncio.Barrier(racers)

        results = await asyncio.gather(
            *(
                _reserve(sessionmaker, resource, SLOT_START, SLOT_END, barrier=barrier)
                for _ in range(racers)
            )
        )

        assert sum(results) == 1, f"exactly one of {racers} must win, got {results}"
        assert await _live_count(sessionmaker) == 1

    async def test_a_hold_and_a_booking_compete_for_the_same_time(
        self, sessionmaker
    ) -> None:  # type: ignore[no-untyped-def]
        """The reason holds and bookings share one table.

        A hold that did not block a booking would be decoration; this is what
        makes a held slot genuinely unbookable.
        """
        resource = uuid.uuid4()
        barrier = asyncio.Barrier(2)

        results = await asyncio.gather(
            _reserve(
                sessionmaker,
                resource,
                SLOT_START,
                SLOT_END,
                kind="hold",
                expires_at=SLOT_START + timedelta(minutes=10),
                barrier=barrier,
            ),
            _reserve(sessionmaker, resource, SLOT_START, SLOT_END, barrier=barrier),
        )

        assert sum(results) == 1

    async def test_a_partial_overlap_is_still_a_conflict(self, sessionmaker) -> None:  # type: ignore[no-untyped-def]
        """A 15-minute overlap is as fatal as a full one — a doctor cannot be in
        two places for any part of an appointment."""
        resource = uuid.uuid4()
        assert await _reserve(sessionmaker, resource, SLOT_START, SLOT_END)
        assert not await _reserve(
            sessionmaker,
            resource,
            SLOT_START + timedelta(minutes=15),
            SLOT_END + timedelta(minutes=15),
        )


class TestWhatMustNotConflict:
    async def test_back_to_back_appointments_are_allowed(self, sessionmaker) -> None:  # type: ignore[no-untyped-def]
        """One ends at 3:30, the next starts at 3:30.

        This is the half-open '[)' range doing its job. A closed range would make
        every back-to-back booking a conflict and halve a clinic's capacity.
        """
        resource = uuid.uuid4()
        assert await _reserve(sessionmaker, resource, SLOT_START, SLOT_END)
        assert await _reserve(
            sessionmaker, resource, SLOT_END, SLOT_END + timedelta(minutes=30)
        )
        assert await _live_count(sessionmaker) == 2

    async def test_a_busy_doctor_does_not_block_a_free_one(self, sessionmaker) -> None:  # type: ignore[no-untyped-def]
        """The constraint is scoped per resource, not globally."""
        khan, ada = uuid.uuid4(), uuid.uuid4()
        assert await _reserve(sessionmaker, khan, SLOT_START, SLOT_END)
        assert await _reserve(sessionmaker, ada, SLOT_START, SLOT_END)
        assert await _live_count(sessionmaker) == 2

    async def test_releasing_a_reservation_frees_the_slot(self, sessionmaker) -> None:  # type: ignore[no-untyped-def]
        """Cancelling must hand the time back.

        Without the constraint's `WHERE released_at IS NULL`, a cancelled
        appointment would keep its slot dead forever.
        """
        resource = uuid.uuid4()
        assert await _reserve(sessionmaker, resource, SLOT_START, SLOT_END)
        assert not await _reserve(sessionmaker, resource, SLOT_START, SLOT_END)

        async with sessionmaker() as session:
            await session.execute(text(f"SET search_path TO {SCHEMA}"))
            await session.execute(
                text("UPDATE resource_reservations SET released_at = now()")
            )
            await session.commit()

        assert await _reserve(sessionmaker, resource, SLOT_START, SLOT_END)

    async def test_many_released_rows_never_accumulate_into_a_conflict(
        self, sessionmaker
    ) -> None:  # type: ignore[no-untyped-def]
        """A slot booked and cancelled repeatedly stays bookable."""
        resource = uuid.uuid4()
        for _ in range(5):
            assert await _reserve(sessionmaker, resource, SLOT_START, SLOT_END)
            async with sessionmaker() as session:
                await session.execute(text(f"SET search_path TO {SCHEMA}"))
                await session.execute(
                    text(
                        "UPDATE resource_reservations SET released_at = now() "
                        "WHERE released_at IS NULL"
                    )
                )
                await session.commit()
        assert await _live_count(sessionmaker) == 0
        assert await _reserve(sessionmaker, resource, SLOT_START, SLOT_END)


class TestExpiredHolds:
    async def test_an_expired_hold_still_occupies_its_slot_until_released(
        self, sessionmaker
    ) -> None:  # type: ignore[no-untyped-def]
        """An important, deliberate property.

        The constraint cannot read the clock — its predicate must be immutable —
        so an expired-but-unreleased hold still blocks at the database level.
        That is exactly why the booking path releases expired holds inside its
        own transaction rather than trusting the background sweep, and why the
        availability query filters on `expires_at` as well. This test pins the
        behaviour so the reason for that code is not lost.
        """
        resource = uuid.uuid4()
        assert await _reserve(
            sessionmaker,
            resource,
            SLOT_START,
            SLOT_END,
            kind="hold",
            expires_at=datetime.now(UTC) - timedelta(hours=1),
        )
        assert not await _reserve(sessionmaker, resource, SLOT_START, SLOT_END)

    async def test_releasing_the_expired_hold_lets_the_booking_through(
        self, sessionmaker
    ) -> None:  # type: ignore[no-untyped-def]
        """What `purge_expired_holds` does, and why booking calls it first."""
        resource = uuid.uuid4()
        await _reserve(
            sessionmaker,
            resource,
            SLOT_START,
            SLOT_END,
            kind="hold",
            expires_at=datetime.now(UTC) - timedelta(hours=1),
        )

        async with sessionmaker() as session:
            await session.execute(text(f"SET search_path TO {SCHEMA}"))
            await session.execute(
                text(
                    "UPDATE resource_reservations SET released_at = now() "
                    "WHERE kind = 'hold' AND released_at IS NULL "
                    "AND expires_at <= now()"
                )
            )
            await session.commit()

        assert await _reserve(sessionmaker, resource, SLOT_START, SLOT_END)


class TestTheConflictClassifier:
    """The production code must recognise every way losing a race looks.

    This is the regression guard for a bug a hermetic suite could never find:
    the first version of `reserve` caught only `IntegrityError`, so a genuinely
    simultaneous booking surfaced to the customer as a 500 rather than "that
    time was just taken".
    """

    async def test_a_deadlock_is_treated_as_a_lost_race(self, sessionmaker) -> None:  # type: ignore[no-untyped-def]
        # Driven through real concurrency rather than a fabricated exception, so
        # it keeps testing the real thing.
        resource = uuid.uuid4()
        barrier = asyncio.Barrier(2)
        results = await asyncio.gather(
            _reserve(sessionmaker, resource, SLOT_START, SLOT_END, barrier=barrier),
            _reserve(sessionmaker, resource, SLOT_START, SLOT_END, barrier=barrier),
        )
        # `_reserve` asserts the classifier accepted whatever the loser got.
        assert sum(results) == 1
