"""Track how long a contact has gone quiet, so the assistant can follow up

A conversation had no notion of waiting. The assistant answered whatever
arrived and then went silent forever, which is the wrong behaviour for
outreach: a candidate who reads a message and gets distracted is exactly the
one worth nudging, and the campaign funnel counted them as "sent, never
replied" with nobody ever asking again.

Two columns carry the whole ladder:

  * `awaiting_reply_since` — when we last spoke and started waiting. NULL means
    we are not waiting on anybody (they replied, or we have signed off), which
    is also what keeps the sweep's query cheap: the overwhelming majority of
    rows are NULL and never match.
  * `followups_sent` — how many nudges have gone out. The sign-off that ends
    the ladder counts as one past the limit, so a signed-off thread can never
    be picked up again without the contact replying first.

Deliberately state on the row rather than a scheduled job or an in-process
timer: this host restarts often and sleeps on idle, and anything held in
memory would forget every pending follow-up on the way down. A timestamp in
Postgres survives that, and a sweep that wakes up late simply finds the
conversation overdue and handles it then.

Revision ID: 0024_conversation_follow_ups
Revises: 0023_unassigned_chat_sessions
Create Date: 2026-08-18
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0024_conversation_follow_ups"
down_revision: str | None = "0023_unassigned_chat_sessions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "whatsapp_conversations",
        sa.Column("awaiting_reply_since", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "whatsapp_conversations",
        sa.Column(
            "followups_sent",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
    )
    # Partial index: the sweep only ever asks for rows that are actually
    # waiting, and those are a small minority. Indexing the NULLs too would
    # cost write throughput on every message for no read benefit.
    op.create_index(
        "ix_whatsapp_conversations_awaiting_reply",
        "whatsapp_conversations",
        ["awaiting_reply_since"],
        postgresql_where=sa.text("awaiting_reply_since IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index(
        "ix_whatsapp_conversations_awaiting_reply",
        table_name="whatsapp_conversations",
    )
    op.drop_column("whatsapp_conversations", "followups_sent")
    op.drop_column("whatsapp_conversations", "awaiting_reply_since")
