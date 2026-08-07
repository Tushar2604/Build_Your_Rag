"""WhatsApp broadcast campaigns

`broadcasts` is one outbound campaign against a connected WhatsApp channel;
`broadcast_recipients` is one row per contact, carrying the delivery funnel
state and a link to the chat_session that the recipient's replies thread into
(so auto-reply reuses the existing WhatsApp conversation machinery).

Revision ID: 0013_broadcasts
Revises: 0012_flow_and_post_call
Create Date: 2026-08-07
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision: str = "0013_broadcasts"
down_revision: str | None = "0012_flow_and_post_call"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "broadcasts",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", pg.UUID(as_uuid=True),
                  sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("chatbot_id", pg.UUID(as_uuid=True),
                  sa.ForeignKey("chatbots.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("whatsapp_channel_id", pg.UUID(as_uuid=True),
                  sa.ForeignKey("whatsapp_channels.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column("message_template", sa.Text, nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="queued"),
        sa.Column("total_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("sent_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("delivered_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("read_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("replied_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("failed_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "broadcast_recipients",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("broadcast_id", pg.UUID(as_uuid=True),
                  sa.ForeignKey("broadcasts.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("tenant_id", pg.UUID(as_uuid=True),
                  sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("phone_number", sa.String(32), nullable=False),
        sa.Column("display_name", sa.String(160), nullable=False, server_default=""),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("error", sa.Text, nullable=False, server_default=""),
        # Twilio message SID. Indexed because the status callback arrives with
        # only this to identify the recipient.
        sa.Column(
            "provider_message_id", sa.String(64), nullable=False, server_default="", index=True
        ),
        sa.Column("session_id", pg.UUID(as_uuid=True),
                  sa.ForeignKey("chat_sessions.id", ondelete="SET NULL"), nullable=True),
        sa.Column("attempts", sa.Integer, nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        # One row per number per campaign — makes a re-uploaded contact list
        # idempotent instead of double-messaging everyone on it.
        sa.UniqueConstraint("broadcast_id", "phone_number", name="uq_broadcast_recipient_phone"),
    )
    # The send sweep's hot query: "next pending recipients for this campaign".
    op.create_index(
        "ix_broadcast_recipients_broadcast_status",
        "broadcast_recipients",
        ["broadcast_id", "status"],
    )

    for table in ("broadcasts", "broadcast_recipients"):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY tenant_isolation ON {table} USING "
            "(tenant_id = current_setting('app.tenant_id', true)::uuid)"
        )


def downgrade() -> None:
    for table in ("broadcast_recipients", "broadcasts"):
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")
    op.drop_index("ix_broadcast_recipients_broadcast_status", table_name="broadcast_recipients")
    op.drop_table("broadcast_recipients")
    op.drop_table("broadcasts")
