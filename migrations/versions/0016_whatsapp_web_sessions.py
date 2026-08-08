"""Personal WhatsApp linking via QR (multi-device)

Two tables:

  * `whatsapp_web_sessions` — lifecycle only (status, QR, linked number). Never
    holds WhatsApp credentials.
  * `whatsapp_web_auth` — the Baileys auth state, written by the Node bridge.
    It lives in Postgres rather than on disk on purpose: the container's
    filesystem is ephemeral on free hosts, and losing these keys would force the
    user to re-scan a QR after every sleep or redeploy. Persisting them here is
    what makes the link survive a restart.

`whatsapp_web_auth` is keyed (session_id, key) because Baileys stores its creds
under one key and each signal pre-key/session under its own — an upsert-per-key
store, not a single blob.

Revision ID: 0016_whatsapp_web_sessions
Revises: 0015_integrations_support_voice
Create Date: 2026-08-08
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision: str = "0016_whatsapp_web_sessions"
down_revision: str | None = "0015_integrations_support_voice"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "whatsapp_web_sessions",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", pg.UUID(as_uuid=True),
                  sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True),
        # SET NULL, not CASCADE: deleting an assistant must not silently unlink
        # the user's personal WhatsApp account.
        sa.Column("chatbot_id", pg.UUID(as_uuid=True),
                  sa.ForeignKey("chatbots.id", ondelete="SET NULL"), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending", index=True),
        sa.Column("phone_number", sa.String(32), nullable=False, server_default=""),
        sa.Column("display_name", sa.String(160), nullable=False, server_default=""),
        # Data-URL PNG. Text, not bytea — it is served straight into an <img src>.
        sa.Column("qr_data_url", sa.Text, nullable=False, server_default=""),
        sa.Column("qr_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text, nullable=False, server_default=""),
        sa.Column("linked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    # The inbound webhook resolves a session by the linked handset's number.
    op.create_index(
        "ix_whatsapp_web_sessions_phone", "whatsapp_web_sessions", ["phone_number"]
    )

    op.create_table(
        "whatsapp_web_auth",
        sa.Column("session_id", pg.UUID(as_uuid=True),
                  sa.ForeignKey("whatsapp_web_sessions.id", ondelete="CASCADE"),
                  primary_key=True),
        sa.Column("key", sa.String(255), primary_key=True),
        sa.Column("value", sa.Text, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
    )

    op.execute("ALTER TABLE whatsapp_web_sessions ENABLE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_isolation ON whatsapp_web_sessions USING "
        "(tenant_id = current_setting('app.tenant_id', true)::uuid)"
    )
    # whatsapp_web_auth has no tenant_id of its own — it is scoped through its
    # session, and is only ever touched by the bridge, never by a tenant request.


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON whatsapp_web_sessions")
    op.drop_table("whatsapp_web_auth")
    op.drop_index("ix_whatsapp_web_sessions_phone", table_name="whatsapp_web_sessions")
    op.drop_table("whatsapp_web_sessions")
