"""Campaign mode + sender, and a fix for polymorphic conversation owners

Three changes, all needed by "create a campaign and choose which WhatsApp number
it sends from":

1. `broadcasts.mode` — `broadcast` (announce only) vs `broadcast_reply` (the
   assistant answers replies). Existing campaigns default to `broadcast_reply`
   because that is what they have been doing.

2. `broadcasts.sender_kind` + `whatsapp_session_id` — a campaign now sends from
   either a Cloud API number (`whatsapp_channels`) or a QR-linked personal
   account (`whatsapp_web_sessions`). Two typed, nullable FKs rather than one
   polymorphic id, so the database still enforces that whichever is set points
   at something real. `whatsapp_channel_id` becomes nullable for the same
   reason.

3. `whatsapp_conversations.whatsapp_channel_id` loses its foreign key. That
   column has always held *either* a channel id or a web-session id — the
   personal-WhatsApp reply path writes a session id into it — so the constraint
   was rejecting the first inbound message on every linked personal number. The
   fix is to drop the constraint the data was already violating, not to pretend
   the column is single-typed. `auto_reply` joins it so an announce-only
   campaign can record a reply without answering it.

Revision ID: 0021_campaign_mode_and_sender
Revises: 0020_chatbot_display_id
Create Date: 2026-08-10
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision: str = "0021_campaign_mode_and_sender"
down_revision: str | None = "0020_chatbot_display_id"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CONV_FK = "whatsapp_conversations_whatsapp_channel_id_fkey"


def upgrade() -> None:
    op.add_column(
        "broadcasts",
        sa.Column("mode", sa.String(20), nullable=False, server_default="broadcast_reply"),
    )
    op.add_column(
        "broadcasts",
        sa.Column("sender_kind", sa.String(16), nullable=False, server_default="cloud_api"),
    )
    op.add_column(
        "broadcasts",
        sa.Column(
            "whatsapp_session_id",
            pg.UUID(as_uuid=True),
            # SET NULL, not CASCADE: unlinking a phone must not delete the
            # history of what was sent from it.
            sa.ForeignKey("whatsapp_web_sessions.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.alter_column("broadcasts", "whatsapp_channel_id", nullable=True)

    op.add_column(
        "whatsapp_conversations",
        sa.Column("auto_reply", sa.Boolean, nullable=False, server_default=sa.true()),
    )
    # Named explicitly rather than reflected: this is Postgres's default name
    # for the constraint 0009 created, and IF EXISTS keeps the migration safe on
    # a database where it was already dropped by hand.
    op.execute(f"ALTER TABLE whatsapp_conversations DROP CONSTRAINT IF EXISTS {_CONV_FK}")


def downgrade() -> None:
    # The FK is not restored: personal-WhatsApp rows now legitimately hold
    # web-session ids, and re-adding it would fail against real data.
    op.drop_column("whatsapp_conversations", "auto_reply")
    op.alter_column("broadcasts", "whatsapp_channel_id", nullable=False)
    op.drop_column("broadcasts", "whatsapp_session_id")
    op.drop_column("broadcasts", "sender_kind")
    op.drop_column("broadcasts", "mode")
