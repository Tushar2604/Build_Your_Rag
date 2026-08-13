"""Let a chat session exist before an assistant is chosen for it

`chat_sessions.chatbot_id` has been NOT NULL since 0001, which was right when
the only way to get a session was to open a chatbot's widget. The WhatsApp
inbox broke that assumption: a QR-linked number receives messages the moment it
is paired, which is usually *before* the user has picked which assistant should
answer them. `_ensure_conversation` duly built a session with `chatbot_id=None`
and the insert died on the NOT NULL — so the bridge event 500'd and the message
was never stored at all, for exactly the case the code comment claimed to
support ("a number with nothing attached still needs somewhere to put its
messages").

Making the column nullable is the honest shape: NULL means "received, nobody is
answering yet". Attaching an assistant back-fills these rows (see
`attach_assistant`), so a thread that arrived before the choice was made starts
being answered rather than staying orphaned forever.

Revision ID: 0023_unassigned_chat_sessions
Revises: 0022_whatsapp_inbox
Create Date: 2026-08-13
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision: str = "0023_unassigned_chat_sessions"
down_revision: str | None = "0022_whatsapp_inbox"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column(
        "chat_sessions",
        "chatbot_id",
        existing_type=pg.UUID(as_uuid=True),
        nullable=True,
    )


def downgrade() -> None:
    # Rows that were only ever possible under the new rule cannot be expressed
    # in the old shape, so they go rather than block the downgrade. Cascades
    # take their messages and WhatsApp conversations with them.
    op.execute(sa.text("DELETE FROM chat_sessions WHERE chatbot_id IS NULL"))
    op.alter_column(
        "chat_sessions",
        "chatbot_id",
        existing_type=pg.UUID(as_uuid=True),
        nullable=False,
    )
