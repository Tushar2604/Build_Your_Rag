"""Give a WhatsApp thread the context an operator actually works from

The inbox could show a conversation and nothing about the person having it.
A thread was a phone number, a preview and an unread count — everything else a
team needs to work a shared number lived in someone's head or another tab: who
owns this chat, whether it is still open, what stage the lead is at, who this
person is and where they came from.

Two shapes carry that:

  * Columns on `whatsapp_conversations` for the facts that are one-per-thread
    and read on every list query — the assignee, the open/closed state, the
    tags, the pin, and the contact card. Denormalised onto the row deliberately:
    the thread list renders all of them, and a join per thread is the query that
    makes an inbox feel slow.
  * A `whatsapp_conversation_notes` table for the internal running commentary,
    which is genuinely one-to-many and appended to rather than edited.

`assignee_id` is ON DELETE SET NULL rather than CASCADE — a teammate leaving
must unassign their threads, never delete them.

Revision ID: 0026_whatsapp_crm_inbox
Revises: 0025_scheduling_foundation
Create Date: 2026-08-29
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0026_whatsapp_crm_inbox"
down_revision: str | None = "0025_scheduling_foundation"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# Every text field defaults to '' rather than NULL, matching the columns already
# on this table: the API returns strings, and a nullable text column means every
# reader has to remember the `or ""`.
_TEXT_COLUMNS: tuple[tuple[str, int], ...] = (
    ("company", 160),
    ("job_title", 120),
    ("email", 254),
    ("city", 120),
    ("country", 120),
    ("linkedin_url", 300),
    ("source", 60),
)


def upgrade() -> None:
    op.add_column(
        "whatsapp_conversations",
        sa.Column("assignee_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_whatsapp_conv_assignee",
        "whatsapp_conversations",
        "users",
        ["assignee_id"],
        ["id"],
        ondelete="SET NULL",
    )
    # Partial: "assigned to me" and "unassigned" are the two filters the inbox
    # offers, and the second one reads NULLs, which this index deliberately
    # skips — a NULL scan is the cheap half of that pair anyway.
    op.create_index(
        "ix_whatsapp_conversations_assignee",
        "whatsapp_conversations",
        ["assignee_id"],
        postgresql_where=sa.text("assignee_id IS NOT NULL"),
    )

    op.add_column(
        "whatsapp_conversations",
        sa.Column(
            "tags",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )
    op.add_column(
        "whatsapp_conversations",
        sa.Column("pinned", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    # 'open' | 'closed'. A string rather than a boolean because "closed" is the
    # first of a set an inbox always grows ("snoozed", "spam"), and widening a
    # boolean later means a second migration and a backfill.
    op.add_column(
        "whatsapp_conversations",
        sa.Column("status", sa.String(16), nullable=False, server_default="open"),
    )
    for name, length in _TEXT_COLUMNS:
        op.add_column(
            "whatsapp_conversations",
            sa.Column(name, sa.String(length), nullable=False, server_default=""),
        )

    op.create_table(
        "whatsapp_conversation_notes",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False, index=True),
        sa.Column(
            "conversation_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("whatsapp_conversations.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "author_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        # Kept alongside the id so a note still says who wrote it after that
        # teammate's account is gone. An audit line that turns into "someone"
        # is not an audit line.
        sa.Column("author_email", sa.String(254), nullable=False, server_default=""),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )

    op.execute("ALTER TABLE whatsapp_conversation_notes ENABLE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_isolation ON whatsapp_conversation_notes "
        "USING (tenant_id = current_setting('app.tenant_id', true)::uuid)"
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON whatsapp_conversation_notes")
    op.drop_table("whatsapp_conversation_notes")
    for name, _ in reversed(_TEXT_COLUMNS):
        op.drop_column("whatsapp_conversations", name)
    op.drop_column("whatsapp_conversations", "status")
    op.drop_column("whatsapp_conversations", "pinned")
    op.drop_column("whatsapp_conversations", "tags")
    op.drop_index(
        "ix_whatsapp_conversations_assignee", table_name="whatsapp_conversations"
    )
    op.drop_constraint(
        "fk_whatsapp_conv_assignee", "whatsapp_conversations", type_="foreignkey"
    )
    op.drop_column("whatsapp_conversations", "assignee_id")
