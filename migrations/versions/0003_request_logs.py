"""per-request evaluation log: rag_request_logs (every request, incl. failures)

Revision ID: 0003_request_logs
Revises: 0002_message_provider
Create Date: 2026-06-27
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision: str = "0003_request_logs"
down_revision: str | None = "0002_message_provider"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "rag_request_logs",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", pg.UUID(as_uuid=True), nullable=False, index=True),
        sa.Column("chatbot_id", pg.UUID(as_uuid=True), nullable=False, index=True),
        sa.Column("session_id", pg.UUID(as_uuid=True), nullable=False, index=True),
        sa.Column("message_id", pg.UUID(as_uuid=True), nullable=True),
        sa.Column("query", sa.Text, nullable=False),
        sa.Column("retrieved", pg.JSONB, nullable=False, server_default="[]"),
        sa.Column("num_retrieved", sa.Integer, nullable=False, server_default="0"),
        sa.Column("max_score", sa.Float, nullable=True),
        sa.Column("no_context", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("refused", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("answer", sa.Text, nullable=True),
        sa.Column("provider", sa.String(40), nullable=True),
        sa.Column("model", sa.String(80), nullable=True),
        sa.Column("tokens_used", sa.Integer, nullable=False, server_default="0"),
        sa.Column("status", sa.String(10), nullable=False, server_default="ok", index=True),
        sa.Column("error", sa.Text, nullable=True),
        sa.Column("latency_ms", sa.Integer, nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, index=True),
    )

    # Tenant isolation policy, consistent with the other tenant-scoped tables
    # (dormant until the app connects as a non-owner role; explicit tenant
    # filters in the repository are the active guard — see 0001_initial).
    op.execute("ALTER TABLE rag_request_logs ENABLE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_isolation ON rag_request_logs USING "
        "(tenant_id = current_setting('app.tenant_id', true)::uuid)"
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON rag_request_logs")
    op.drop_table("rag_request_logs")
