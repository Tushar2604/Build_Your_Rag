"""hiring agent executor state: hiring_agent_memory.execution (plan/cursor/approval)

Additive only — adds one nullable JSONB column to the existing hiring-agent
memory table so a plan-driven execution can be paused (e.g. awaiting human
approval) and resumed. No existing column is altered; non-breaking.

Revision ID: 0006_hiring_execution_state
Revises: 0005_hiring_agent_memory
Create Date: 2026-07-04
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision: str = "0006_hiring_execution_state"
down_revision: str | None = "0005_hiring_agent_memory"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Holds {goal, plan[], cursor, pending_approval}. Nullable so existing rows
    # (pure workflow-engine runs, no executor state) are unaffected.
    op.add_column(
        "hiring_agent_memory",
        sa.Column("execution", pg.JSONB, nullable=True),
    )


def downgrade() -> None:
    op.drop_column("hiring_agent_memory", "execution")
