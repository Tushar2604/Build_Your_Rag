"""hiring agent persistent memory: hiring_agent_memory (resumable run state)

Additive only — creates one new table. No existing table is altered, so this is
a non-breaking change. The table backs the Hiring Agent's persistent memory
(completed steps, tool outputs, LLM reasoning, conversation, candidate
decisions) and enables resume-after-interruption via its `status` column.

Revision ID: 0005_hiring_agent_memory
Revises: 0004_public_widget
Create Date: 2026-07-04
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision: str = "0005_hiring_agent_memory"
down_revision: str | None = "0004_public_widget"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "hiring_agent_memory",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", pg.UUID(as_uuid=True), nullable=False, index=True),
        # running | completed | failed | interrupted — non-terminal = resumable.
        sa.Column("status", sa.String(20), nullable=False, server_default="running", index=True),
        sa.Column("current_state", sa.String(40), nullable=False, server_default="IDLE"),
        sa.Column("completed_steps", pg.JSONB, nullable=False, server_default="[]"),
        sa.Column("tool_outputs", pg.JSONB, nullable=False, server_default="[]"),
        sa.Column("llm_reasoning", pg.JSONB, nullable=False, server_default="[]"),
        sa.Column("conversation", pg.JSONB, nullable=False, server_default="[]"),
        sa.Column("candidate_decisions", pg.JSONB, nullable=False, server_default="[]"),
        sa.Column("error", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, index=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )

    # Tenant isolation policy, consistent with the other tenant-scoped tables
    # (dormant until the app connects as a non-owner role; explicit tenant
    # filters in the repository are the active guard — see 0001_initial).
    op.execute("ALTER TABLE hiring_agent_memory ENABLE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_isolation ON hiring_agent_memory USING "
        "(tenant_id = current_setting('app.tenant_id', true)::uuid)"
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON hiring_agent_memory")
    op.drop_table("hiring_agent_memory")
