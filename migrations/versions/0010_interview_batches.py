"""Bulk interview invites: interview_batches + interview_batch_candidates

Additive only. `interviews.window_closes_at` (nullable) lets a batch-created
interview carry a self-service deadline instead of a fixed calendar slot;
existing single-scheduled rows stay NULL and behave exactly as before.

Revision ID: 0010_interview_batches
Revises: 0009_whatsapp
Create Date: 2026-07-28
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision: str = "0010_interview_batches"
down_revision: str | None = "0009_whatsapp"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_RLS_TABLES = ("interview_batches", "interview_batch_candidates")


def upgrade() -> None:
    op.add_column("interviews", sa.Column("window_closes_at", sa.DateTime(timezone=True), nullable=True))

    op.create_table(
        "interview_batches",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", pg.UUID(as_uuid=True),
                  sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("role_title", sa.String(200), nullable=False, server_default=""),
        sa.Column("job_document_id", pg.UUID(as_uuid=True),
                  sa.ForeignKey("documents.id", ondelete="CASCADE"), nullable=False),
        sa.Column("window_opens_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("window_closes_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="collecting", index=True),
        sa.Column("total_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("sent_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("failed_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "interview_batch_candidates",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", pg.UUID(as_uuid=True),
                  sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("batch_id", pg.UUID(as_uuid=True),
                  sa.ForeignKey("interview_batches.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("resume_document_id", pg.UUID(as_uuid=True),
                  sa.ForeignKey("documents.id", ondelete="CASCADE"), nullable=False),
        sa.Column("resume_filename", sa.String(500), nullable=False, server_default=""),
        sa.Column("candidate_name", sa.String(200), nullable=False, server_default=""),
        sa.Column("candidate_email", sa.String(320), nullable=False, server_default=""),
        sa.Column("status", sa.String(20), nullable=False, server_default="ingesting", index=True),
        sa.Column("error", sa.String(500), nullable=True),
        sa.Column("interview_id", pg.UUID(as_uuid=True),
                  sa.ForeignKey("interviews.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
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
    op.drop_table("interview_batch_candidates")
    op.drop_table("interview_batches")
    op.drop_column("interviews", "window_closes_at")
