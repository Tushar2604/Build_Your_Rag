"""chatbot channel: text vs voice

Additive only — adds one NOT NULL column with a default so existing chatbots
(all pre-dating this feature) become "text", their current behavior. No
existing column is altered; non-breaking.

Revision ID: 0007_chatbot_channel
Revises: 0006_hiring_execution_state
Create Date: 2026-07-25
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007_chatbot_channel"
down_revision: str | None = "0006_hiring_execution_state"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "chatbots",
        sa.Column("channel", sa.String(16), nullable=False, server_default="text"),
    )


def downgrade() -> None:
    op.drop_column("chatbots", "channel")
