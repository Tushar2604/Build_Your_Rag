"""Virtual Interview: interviews + google_oauth_connections tables

Additive only — two new tables, no existing schema touched. `interviews`
holds the full interview lifecycle (schedule -> conduct -> score); the
candidate has no account, so `access_token` (unique, indexed) is their only
credential. `google_oauth_connections` is one row per tenant holding that
tenant's "Connect Google Calendar" tokens (blank/absent = not connected,
scheduling still works, just skips the calendar step).

Revision ID: 0008_interviews
Revises: 0007_chatbot_channel
Create Date: 2026-07-25
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision: str = "0008_interviews"
down_revision: str | None = "0007_chatbot_channel"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_RLS_TABLES = ("interviews", "google_oauth_connections")


def upgrade() -> None:
    op.create_table(
        "interviews",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", pg.UUID(as_uuid=True),
                  sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("candidate_name", sa.String(200), nullable=False, server_default=""),
        sa.Column("candidate_email", sa.String(320), nullable=False),
        sa.Column("role_title", sa.String(200), nullable=False, server_default=""),
        sa.Column("job_document_id", pg.UUID(as_uuid=True),
                  sa.ForeignKey("documents.id", ondelete="CASCADE"), nullable=False),
        sa.Column("resume_document_id", pg.UUID(as_uuid=True),
                  sa.ForeignKey("documents.id", ondelete="CASCADE"), nullable=False),
        sa.Column("scheduled_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="scheduled", index=True),
        sa.Column("access_token", sa.String(64), nullable=False, unique=True, index=True),
        sa.Column("questions", pg.JSONB, nullable=False, server_default="[]"),
        sa.Column("transcript", pg.JSONB, nullable=False, server_default="[]"),
        sa.Column("current_question_index", sa.Integer, nullable=False, server_default="0"),
        sa.Column("google_event_id", sa.String(255), nullable=True),
        sa.Column("calendar_link", sa.String(1024), nullable=True),
        sa.Column("report_storage_key", sa.String(512), nullable=True),
        sa.Column("overall_score", sa.Float, nullable=True),
        sa.Column("overall_verdict", sa.String(32), nullable=True),
        sa.Column("scores", pg.JSONB, nullable=False, server_default="[]"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "google_oauth_connections",
        sa.Column("tenant_id", pg.UUID(as_uuid=True),
                  sa.ForeignKey("tenants.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("access_token", sa.Text, nullable=False),
        sa.Column("refresh_token", sa.Text, nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("scope", sa.String(500), nullable=False, server_default=""),
        sa.Column("connected_email", sa.String(320), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )

    # --- Row-Level Security (defense-in-depth, same caveat as 0001: dormant
    # until the app connects as a non-owner DB role; explicit per-query tenant
    # filters in the repositories are the active guard until then) ---
    for table in _RLS_TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY tenant_isolation ON {table} USING "
            f"(tenant_id = current_setting('app.tenant_id', true)::uuid)"
        )


def downgrade() -> None:
    for table in _RLS_TABLES:
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")
    op.drop_table("google_oauth_connections")
    op.drop_table("interviews")
