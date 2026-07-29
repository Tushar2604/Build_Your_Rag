"""Team invites + custom interview questions

Additive only. `tenant_invites` lets an Owner/Admin bring a teammate into
their existing tenant with a chosen role (activates the `Role` column that
already exists on `users` but has never been settable by anyone but the
registering owner). `interview_batches.custom_questions` lets a bulk batch
carry admin-supplied questions alongside the auto-generated ones, mirroring
the same field added to individual interviews via the existing `questions`
JSONB column (no schema change needed there).

Revision ID: 0011_team_and_custom_questions
Revises: 0010_interview_batches
Create Date: 2026-07-29
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision: str = "0011_team_and_custom_questions"
down_revision: str | None = "0010_interview_batches"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_RLS_TABLES = ("tenant_invites",)


def upgrade() -> None:
    op.create_table(
        "tenant_invites",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", pg.UUID(as_uuid=True),
                  sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("email", sa.String(255), nullable=False, index=True),
        sa.Column("role", sa.String(20), nullable=False, server_default="member"),
        sa.Column("token", sa.String(64), nullable=False, unique=True, index=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending", index=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.add_column(
        "interview_batches",
        sa.Column("custom_questions", pg.JSONB, nullable=False, server_default="[]"),
    )

    # --- Row-Level Security (defense-in-depth, same caveat as 0001/0008) ---
    for table in _RLS_TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY tenant_isolation ON {table} USING "
            f"(tenant_id = current_setting('app.tenant_id', true)::uuid)"
        )


def downgrade() -> None:
    for table in _RLS_TABLES:
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")
    op.drop_column("interview_batches", "custom_questions")
    op.drop_table("tenant_invites")
