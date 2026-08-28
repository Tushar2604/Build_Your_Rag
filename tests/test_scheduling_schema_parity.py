"""Guard: migration 0025 really creates what the scheduling code assumes.

Same technique as `test_schema_parity.py` — render the Alembic DDL offline and
diff it against the ORM — because the realistic failure when adding a table in
two places is a column that exists on the model and in no migration. The app then
works locally against a `create_all` database and 500s in production on the first
query.

Beyond column parity, this pins the four pieces of DDL the design depends on:
the exclusion constraint (without which two customers can book the same slot),
the idempotency index (without which a retried POST double-books), RLS on every
table (without which the tenant guard has no backstop), and the indexes the
availability query needs to not be a sequential scan.

No database required.
"""

from __future__ import annotations

import io
import re

import pytest
from alembic import command
from alembic.config import Config
from src.infrastructure.persistence import models as m

SCHEDULING_TABLES = {
    "locations": m.LocationModel,
    "services": m.ServiceModel,
    "resources": m.ResourceModel,
    "service_resources": m.ServiceResourceModel,
    "availability_rules": m.AvailabilityRuleModel,
    "blocked_periods": m.BlockedPeriodModel,
    "appointments": m.AppointmentModel,
    "appointment_status_history": m.AppointmentStatusHistoryModel,
    "resource_reservations": m.ResourceReservationModel,
}


@pytest.fixture(scope="module")
def migration_sql() -> str:
    """Offline DDL for revision 0025 alone — no database, no network."""
    buffer = io.StringIO()
    config = Config("alembic.ini")
    config.attributes["configure_logger"] = False
    config.output_buffer = buffer
    command.upgrade(
        config, "0024_conversation_follow_ups:0025_scheduling_foundation", sql=True
    )
    sql = buffer.getvalue()
    assert sql.strip(), "offline migration render produced no SQL"
    return sql


def _migrated_columns(sql: str, table: str) -> set[str]:
    match = re.search(rf"CREATE TABLE {table} \((.*?)\n\);", sql, re.S)
    assert match, f"{table} is never created by a migration"
    constraints = ("PRIMARY KEY", "FOREIGN KEY", "UNIQUE", "CONSTRAINT", "CHECK", "EXCLUDE")
    columns = set()
    for line in match.group(1).splitlines():
        line = line.strip().rstrip(",")
        if not line or line.startswith(constraints):
            continue
        columns.add(line.split()[0])
    columns.update(re.findall(rf"ALTER TABLE {table} ADD COLUMN (\w+)", sql))
    return columns


@pytest.mark.parametrize("table", sorted(SCHEDULING_TABLES))
def test_every_orm_column_is_migrated(migration_sql: str, table: str) -> None:
    orm_columns = {c.name for c in SCHEDULING_TABLES[table].__table__.columns}
    missing = orm_columns - _migrated_columns(migration_sql, table)
    assert not missing, f"{table} model has columns no migration creates: {sorted(missing)}"


@pytest.mark.parametrize("table", sorted(SCHEDULING_TABLES))
def test_no_migrated_column_is_missing_from_the_orm(migration_sql: str, table: str) -> None:
    orm_columns = {c.name for c in SCHEDULING_TABLES[table].__table__.columns}
    orphaned = _migrated_columns(migration_sql, table) - orm_columns
    assert not orphaned, f"{table} has migrated columns the ORM never reads: {sorted(orphaned)}"


class TestTheDoubleBookingGuard:
    """The constraint that makes spec section 12 true rather than aspirational."""

    def test_btree_gist_is_installed_before_the_constraint_needs_it(
        self, migration_sql: str
    ) -> None:
        # The constraint mixes btree equality on a uuid with GiST range overlap
        # in one index, which core Postgres cannot do without this extension.
        assert "CREATE EXTENSION IF NOT EXISTS btree_gist" in migration_sql
        assert migration_sql.index("CREATE EXTENSION IF NOT EXISTS btree_gist") < (
            migration_sql.index("no_overlapping_reservations")
        )

    def test_overlapping_reservations_are_forbidden_by_the_database(
        self, migration_sql: str
    ) -> None:
        # Application-level checking cannot close the gap between "is it free?"
        # and INSERT. This can.
        assert "EXCLUDE USING gist" in migration_sql
        assert "resource_id WITH =" in migration_sql
        assert "WITH &&" in migration_sql

    def test_the_constraint_only_covers_live_reservations(
        self, migration_sql: str
    ) -> None:
        # Without the WHERE clause a cancelled appointment would keep its slot
        # blocked forever, because its row still overlaps.
        constraint = re.search(
            r"ADD CONSTRAINT no_overlapping_reservations(.*?);", migration_sql, re.S
        )
        assert constraint, "the exclusion constraint is missing"
        assert "WHERE (released_at IS NULL)" in constraint.group(1)

    def test_the_range_is_half_open(self, migration_sql: str) -> None:
        # '[)' is what makes an appointment ending at 3pm and one starting at
        # 3pm not a conflict — matching the domain engine's Interval.overlaps.
        assert "tstzrange(starts_at, ends_at, '[)')" in migration_sql

    def test_a_retried_booking_cannot_create_a_second_appointment(
        self, migration_sql: str
    ) -> None:
        assert "CREATE UNIQUE INDEX uq_appointments_idempotency_key" in migration_sql
        # Partial, so the many appointments booked WITHOUT a key do not all
        # collide with each other on an empty string.
        assert re.search(
            r"uq_appointments_idempotency_key.*?WHERE idempotency_key <> ''",
            migration_sql,
            re.S,
        )


class TestTenantIsolation:
    @pytest.mark.parametrize("table", sorted(SCHEDULING_TABLES))
    def test_every_scheduling_table_has_row_level_security(
        self, migration_sql: str, table: str
    ) -> None:
        assert f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY" in migration_sql
        assert f"CREATE POLICY tenant_isolation ON {table}" in migration_sql

    @pytest.mark.parametrize("table", sorted(SCHEDULING_TABLES))
    def test_every_scheduling_table_carries_a_tenant(self, table: str) -> None:
        # An RLS policy on a table with no tenant_id would not compile; this
        # catches the mistake at the model, where it starts.
        columns = {c.name for c in SCHEDULING_TABLES[table].__table__.columns}
        assert "tenant_id" in columns


class TestReferentialChoices:
    def test_deleting_a_branch_cannot_erase_its_appointments(
        self, migration_sql: str
    ) -> None:
        # RESTRICT, not CASCADE. The UI deactivates a location instead, and
        # history survives.
        create = re.search(r"CREATE TABLE appointments \((.*?)\n\);", migration_sql, re.S)
        assert create
        for column in ("location_id", "service_id"):
            fk = re.search(
                rf"FOREIGN KEY\({column}\) REFERENCES \w+ \(id\)([^,\n]*)", create.group(1)
            )
            assert fk, f"{column} has no foreign key"
            assert "ON DELETE RESTRICT" in fk.group(1)

    def test_closing_a_branch_does_not_delete_the_staff_who_worked_there(
        self, migration_sql: str
    ) -> None:
        create = re.search(r"CREATE TABLE resources \((.*?)\n\);", migration_sql, re.S)
        assert create
        for column in ("location_id", "user_id"):
            fk = re.search(
                rf"FOREIGN KEY\({column}\) REFERENCES \w+ \(id\)([^,\n]*)", create.group(1)
            )
            assert fk and "ON DELETE SET NULL" in fk.group(1)

    def test_history_follows_its_appointment(self, migration_sql: str) -> None:
        create = re.search(
            r"CREATE TABLE appointment_status_history \((.*?)\n\);", migration_sql, re.S
        )
        assert create
        fk = re.search(
            r"FOREIGN KEY\(appointment_id\) REFERENCES appointments \(id\)([^,\n]*)",
            create.group(1),
        )
        assert fk and "ON DELETE CASCADE" in fk.group(1)


class TestQueryPerformance:
    """Spec section 66: availability must not scan the appointment table."""

    def test_the_availability_busy_lookup_is_indexed(self, migration_sql: str) -> None:
        assert "ix_resource_reservations_lookup" in migration_sql
        # Partial on live rows: released reservations are the majority over time
        # and are never read by the availability path.
        assert re.search(
            r"ix_resource_reservations_lookup.*?WHERE released_at IS NULL",
            migration_sql,
            re.S,
        )

    def test_the_calendar_window_query_is_indexed(self, migration_sql: str) -> None:
        assert "ix_appointments_tenant_window" in migration_sql
        assert "ix_appointments_tenant_status_window" in migration_sql

    def test_the_availability_rule_lookup_is_indexed(self, migration_sql: str) -> None:
        # The engine's hot path: every rule for a set of owners, per weekday.
        assert "ix_availability_rules_owner" in migration_sql

    def test_the_hold_expiry_sweep_is_indexed(self, migration_sql: str) -> None:
        # Otherwise every tick scans every reservation ever made.
        assert "ix_resource_reservations_expiring" in migration_sql


class TestDowngrade:
    def test_the_migration_can_be_rolled_back(self) -> None:
        buffer = io.StringIO()
        config = Config("alembic.ini")
        config.attributes["configure_logger"] = False
        config.output_buffer = buffer
        command.downgrade(
            config, "0025_scheduling_foundation:0024_conversation_follow_ups", sql=True
        )
        sql = buffer.getvalue()
        for table in SCHEDULING_TABLES:
            assert f"DROP TABLE {table}" in sql, f"{table} is never dropped"

    def test_rollback_drops_children_before_parents(self) -> None:
        buffer = io.StringIO()
        config = Config("alembic.ini")
        config.attributes["configure_logger"] = False
        config.output_buffer = buffer
        command.downgrade(
            config, "0025_scheduling_foundation:0024_conversation_follow_ups", sql=True
        )
        sql = buffer.getvalue()
        # Reservations reference appointments, which reference locations. Any
        # other order fails on a foreign key at rollback time.
        assert sql.index("DROP TABLE resource_reservations") < sql.index(
            "DROP TABLE appointments"
        )
        assert sql.index("DROP TABLE appointments") < sql.index("DROP TABLE locations")
