"""public widget: chatbots.public_key, allowed_origins, widget_config

Revision ID: 0004_public_widget
Revises: 0003_request_logs
Create Date: 2026-06-27
"""
from __future__ import annotations

import secrets
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision: str = "0004_public_widget"
down_revision: str | None = "0003_request_logs"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 1. Add columns. public_key starts nullable so existing rows can be
    #    backfilled with distinct keys before the unique/not-null constraints.
    op.add_column("chatbots", sa.Column("public_key", sa.String(64), nullable=True))
    op.add_column(
        "chatbots",
        sa.Column("allowed_origins", pg.JSONB, nullable=False, server_default="[]"),
    )
    op.add_column(
        "chatbots",
        sa.Column("widget_config", pg.JSONB, nullable=False, server_default="{}"),
    )

    # 2. Backfill a unique publishable key for every existing chatbot.
    conn = op.get_bind()
    rows = conn.execute(sa.text("SELECT id FROM chatbots WHERE public_key IS NULL")).fetchall()
    for (chatbot_id,) in rows:
        conn.execute(
            sa.text("UPDATE chatbots SET public_key = :key WHERE id = :id"),
            {"key": f"pk_{secrets.token_urlsafe(24)}", "id": chatbot_id},
        )

    # 3. Enforce not-null + uniqueness now that every row has a key.
    op.alter_column("chatbots", "public_key", nullable=False)
    op.create_index(
        "ix_chatbots_public_key", "chatbots", ["public_key"], unique=True
    )


def downgrade() -> None:
    op.drop_index("ix_chatbots_public_key", table_name="chatbots")
    op.drop_column("chatbots", "widget_config")
    op.drop_column("chatbots", "allowed_origins")
    op.drop_column("chatbots", "public_key")
