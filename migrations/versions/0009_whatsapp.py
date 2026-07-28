"""WhatsApp channel: whatsapp_channels + whatsapp_conversations tables

Additive only. `whatsapp_channels` is one row per chatbot deployed to
WhatsApp via Twilio (1:1 both ways). `whatsapp_conversations` maps an inbound
sender's phone number to a persistent chat_session, so WhatsApp gets the
same multi-turn memory as the web widget.

Revision ID: 0009_whatsapp
Revises: 0008_interviews
Create Date: 2026-07-26
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision: str = "0009_whatsapp"
down_revision: str | None = "0008_interviews"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "whatsapp_channels",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", pg.UUID(as_uuid=True),
                  sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("chatbot_id", pg.UUID(as_uuid=True),
                  sa.ForeignKey("chatbots.id", ondelete="CASCADE"), nullable=False, unique=True),
        sa.Column("phone_number", sa.String(32), nullable=False, unique=True, index=True),
        sa.Column("twilio_account_sid", sa.String(64), nullable=False),
        sa.Column("twilio_auth_token", sa.Text, nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="active"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "whatsapp_conversations",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("whatsapp_channel_id", pg.UUID(as_uuid=True),
                  sa.ForeignKey("whatsapp_channels.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("phone_number", sa.String(32), nullable=False),
        sa.Column("session_id", pg.UUID(as_uuid=True),
                  sa.ForeignKey("chat_sessions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("whatsapp_channel_id", "phone_number", name="uq_whatsapp_conv_channel_phone"),
    )

    # RLS on whatsapp_channels (defense-in-depth, same caveat as prior
    # migrations: dormant until the app connects as a non-owner DB role).
    # whatsapp_conversations has no tenant_id of its own — it's scoped
    # through its channel, so it's excluded from this per-row policy.
    op.execute("ALTER TABLE whatsapp_channels ENABLE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_isolation ON whatsapp_channels USING "
        "(tenant_id = current_setting('app.tenant_id', true)::uuid)"
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON whatsapp_channels")
    op.drop_table("whatsapp_conversations")
    op.drop_table("whatsapp_channels")
