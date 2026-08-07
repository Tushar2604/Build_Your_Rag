"""Guard: every ORM column on the new tables must exist in a migration.

The realistic failure mode when adding a table in two places is a column that
exists on the model but was never migrated — the app then works locally against
a `create_all` database and 500s in production on the first query. This diffs
the Alembic offline DDL against the ORM metadata so that mismatch fails CI
rather than a deploy.
"""

from __future__ import annotations

import io
import re

import pytest
from alembic import command
from alembic.config import Config
from src.infrastructure.persistence import models as m

# Tables introduced by 0012/0013, plus the column added to an existing table.
NEW_TABLES = {
    "post_call_configs": m.PostCallConfigModel,
    "post_call_deliveries": m.PostCallDeliveryModel,
    "broadcasts": m.BroadcastModel,
    "broadcast_recipients": m.BroadcastRecipientModel,
}


# Rendered as an explicit range rather than <base>:head, because data
# migrations issue real SELECTs and can't run offline — 0004 (publishable-key
# backfill) below, 0014 (prompt backfill) above. 0012 and 0013 are the two
# revisions that carry the DDL this file checks.
FIRST_NEW_REVISION = "0011_team_and_custom_questions"
LAST_DDL_REVISION = "0013_broadcasts"


@pytest.fixture(scope="module")
def migration_sql() -> str:
    """Offline DDL for revisions 0012 and 0013 — no database required."""
    buffer = io.StringIO()
    config = Config("alembic.ini")
    config.attributes["configure_logger"] = False
    # `output_buffer` (not `stdout`) is what offline mode writes DDL to.
    config.output_buffer = buffer
    command.upgrade(config, f"{FIRST_NEW_REVISION}:{LAST_DDL_REVISION}", sql=True)
    sql = buffer.getvalue()
    assert sql.strip(), "offline migration render produced no SQL"
    return sql


def _migrated_columns(sql: str, table: str) -> set[str]:
    match = re.search(rf"CREATE TABLE {table} \((.*?)\n\);", sql, re.S)
    assert match, f"{table} is never created by a migration"
    constraints = ("PRIMARY KEY", "FOREIGN KEY", "UNIQUE", "CONSTRAINT", "CHECK")
    columns = set()
    for line in match.group(1).splitlines():
        line = line.strip().rstrip(",")
        if not line or line.startswith(constraints):
            continue
        columns.add(line.split()[0])
    return columns


@pytest.mark.parametrize("table", sorted(NEW_TABLES))
def test_every_orm_column_is_migrated(migration_sql: str, table: str) -> None:
    model = NEW_TABLES[table]
    orm_columns = {c.name for c in model.__table__.columns}
    missing = orm_columns - _migrated_columns(migration_sql, table)
    assert not missing, f"{table} model has columns no migration creates: {sorted(missing)}"


@pytest.mark.parametrize("table", sorted(NEW_TABLES))
def test_no_migrated_column_is_missing_from_the_orm(migration_sql: str, table: str) -> None:
    model = NEW_TABLES[table]
    orm_columns = {c.name for c in model.__table__.columns}
    orphaned = _migrated_columns(migration_sql, table) - orm_columns
    assert not orphaned, f"{table} has migrated columns the ORM never reads: {sorted(orphaned)}"


def test_flow_sections_column_is_added_to_chatbots(migration_sql: str) -> None:
    assert "flow_sections" in {c.name for c in m.ChatbotModel.__table__.columns}
    assert re.search(r"ALTER TABLE chatbots ADD COLUMN flow_sections", migration_sql)


def test_flow_sections_backfills_existing_rows(migration_sql: str) -> None:
    # Without a server default, every pre-existing chatbot row would read NULL
    # and the mapper would show an empty flow for bots that never opted out.
    assert re.search(
        r"ADD COLUMN flow_sections JSONB DEFAULT '\[\]'::jsonb NOT NULL", migration_sql
    )


def test_dedupe_and_idempotency_constraints_exist(migration_sql: str) -> None:
    # Both are load-bearing: the first stops a double post-call dispatch, the
    # second stops a re-uploaded contact list double-messaging everyone.
    assert "uq_post_call_delivery_config_session UNIQUE (config_id, session_id)" in migration_sql
    assert "uq_broadcast_recipient_phone UNIQUE (broadcast_id, phone_number)" in migration_sql


def test_new_tenant_scoped_tables_have_rls(migration_sql: str) -> None:
    for table in NEW_TABLES:
        assert f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY" in migration_sql
        assert f"CREATE POLICY tenant_isolation ON {table}" in migration_sql


def test_status_callback_lookup_column_is_indexed(migration_sql: str) -> None:
    # Twilio callbacks arrive keyed only on the message SID; without this index
    # every callback is a sequential scan of the recipients table.
    assert re.search(
        r"CREATE INDEX ix_broadcast_recipients_provider_message_id", migration_sql
    )


def test_send_sweep_query_is_indexed(migration_sql: str) -> None:
    assert "ix_broadcast_recipients_broadcast_status" in migration_sql
