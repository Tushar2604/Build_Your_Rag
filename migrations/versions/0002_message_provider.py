"""add provider column to chat_messages (analytics: provider-mix slice)

Revision ID: 0002_message_provider
Revises: 0001_initial
Create Date: 2026-06-27
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002_message_provider"
down_revision: str | None = "0001_initial"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Nullable: user messages and answers written before this column existed
    # legitimately have no provider.
    op.add_column(
        "chat_messages",
        sa.Column("provider", sa.String(40), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("chat_messages", "provider")
