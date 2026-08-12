"""WhatsApp inbox: message attachments and conversation list metadata

Two shapes of change, both in service of showing a real chat window for a
linked number rather than just "connected".

`chat_messages` gains attachment columns. They are deliberately separate
columns rather than reusing `citations` (JSONB): the mapper reads that column
as a list of `Citation` dicts with unguarded key access, so putting anything
else in it breaks every existing conversation on read.

`whatsapp_conversations` gains the fields an inbox list needs to render in one
query — last message, its preview, unread count, whether the thread has an
attachment. Without them, drawing a thread list means one message query per
conversation. It also finally gains `tenant_id`: the table was created without
one (migration 0009) on the reasoning that it is "scoped through its channel",
but an inbox queries it directly, so it needs to be scopable and RLS-guarded on
its own.

Revision ID: 0022_whatsapp_inbox
Revises: 0021_campaign_mode_and_sender
Create Date: 2026-08-12
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision: str = "0022_whatsapp_inbox"
down_revision: str | None = "0021_campaign_mode_and_sender"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # --- Attachments on messages ---------------------------------------
    # All nullable: every existing row is a text message, and the inbound path
    # writes these only when WhatsApp actually delivered media.
    op.add_column("chat_messages", sa.Column("media_kind", sa.String(20), nullable=True))
    op.add_column("chat_messages", sa.Column("media_mime_type", sa.String(160), nullable=True))
    op.add_column("chat_messages", sa.Column("media_filename", sa.String(255), nullable=True))
    # Storage key, not a URL: the bytes live in R2 or on local disk behind
    # `container.storage`, and the API streams them back through an authorized
    # endpoint rather than exposing bucket URLs to the browser.
    op.add_column("chat_messages", sa.Column("media_storage_key", sa.String(512), nullable=True))
    op.add_column("chat_messages", sa.Column("media_size_bytes", sa.Integer, nullable=True))
    # WhatsApp's own message id. The socket can redeliver on reconnect, and
    # without this there is nothing to deduplicate on.
    op.add_column(
        "chat_messages", sa.Column("provider_message_id", sa.String(128), nullable=True)
    )

    # Partial index: the "has attachment" filter only ever looks for non-null
    # rows, and attachments are a small minority of messages.
    op.create_index(
        "ix_chat_messages_media",
        "chat_messages",
        ["session_id", "media_kind"],
        postgresql_where=sa.text("media_kind IS NOT NULL"),
    )
    # Dedupe lookups are by (session, provider id); partial for the same reason.
    op.create_index(
        "ix_chat_messages_provider_msg",
        "chat_messages",
        ["session_id", "provider_message_id"],
        postgresql_where=sa.text("provider_message_id IS NOT NULL"),
    )

    # --- Inbox metadata on conversations --------------------------------
    op.add_column(
        "whatsapp_conversations", sa.Column("tenant_id", pg.UUID(as_uuid=True), nullable=True)
    )
    op.add_column(
        "whatsapp_conversations", sa.Column("display_name", sa.String(160), nullable=False, server_default="")
    )
    op.add_column(
        "whatsapp_conversations",
        sa.Column("last_message_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "whatsapp_conversations",
        sa.Column("last_message_preview", sa.String(300), nullable=False, server_default=""),
    )
    op.add_column(
        "whatsapp_conversations",
        sa.Column("unread_count", sa.Integer, nullable=False, server_default="0"),
    )
    op.add_column(
        "whatsapp_conversations",
        sa.Column("has_attachment", sa.Boolean, nullable=False, server_default=sa.false()),
    )

    # Backfill tenant_id from the chat session each conversation already points
    # at, so existing threads are visible in the inbox instead of orphaned by
    # the RLS policy added below.
    op.execute(
        """
        UPDATE whatsapp_conversations c
           SET tenant_id = s.tenant_id
        FROM chat_sessions s
        WHERE s.id = c.session_id AND c.tenant_id IS NULL
        """
    )
    # Seed the list metadata from existing history so migrated threads do not
    # all render as empty with no timestamp.
    op.execute(
        """
        UPDATE whatsapp_conversations c
           SET last_message_at = m.created_at,
               last_message_preview = left(m.content, 300)
        FROM (
            SELECT DISTINCT ON (session_id) session_id, created_at, content
              FROM chat_messages
             ORDER BY session_id, created_at DESC
        ) m
        WHERE m.session_id = c.session_id
        """
    )
    # Any row whose session vanished cannot be scoped or shown; deleting is
    # correct because the conversation is unreachable without its session.
    op.execute("DELETE FROM whatsapp_conversations WHERE tenant_id IS NULL")
    op.alter_column("whatsapp_conversations", "tenant_id", nullable=False)

    op.create_index(
        "ix_whatsapp_conversations_tenant", "whatsapp_conversations", ["tenant_id"]
    )
    # The inbox list query: threads for one number, newest first.
    op.create_index(
        "ix_whatsapp_conversations_owner_recent",
        "whatsapp_conversations",
        ["whatsapp_channel_id", sa.text("last_message_at DESC NULLS LAST")],
    )

    op.execute("ALTER TABLE whatsapp_conversations ENABLE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_isolation ON whatsapp_conversations USING "
        "(tenant_id = current_setting('app.tenant_id', true)::uuid)"
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON whatsapp_conversations")
    op.execute("ALTER TABLE whatsapp_conversations DISABLE ROW LEVEL SECURITY")
    op.drop_index("ix_whatsapp_conversations_owner_recent", table_name="whatsapp_conversations")
    op.drop_index("ix_whatsapp_conversations_tenant", table_name="whatsapp_conversations")
    for column in (
        "has_attachment",
        "unread_count",
        "last_message_preview",
        "last_message_at",
        "display_name",
        "tenant_id",
    ):
        op.drop_column("whatsapp_conversations", column)

    op.drop_index("ix_chat_messages_provider_msg", table_name="chat_messages")
    op.drop_index("ix_chat_messages_media", table_name="chat_messages")
    for column in (
        "provider_message_id",
        "media_size_bytes",
        "media_storage_key",
        "media_filename",
        "media_mime_type",
        "media_kind",
    ):
        op.drop_column("chat_messages", column)
