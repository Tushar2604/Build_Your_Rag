"""Short, stable, human-quotable id per assistant

UUIDs are the primary key and always will be, but nobody reads one aloud or
types it into a support ticket. `display_id` is the number the UI shows as
`#236637`: short enough to say, permanent, and never reused.

A Postgres sequence assigns it rather than the application, because that is the
only way to guarantee uniqueness under concurrent creates without a round-trip
and a retry loop. Existing rows are numbered by `created_at`, so the oldest
assistant gets the lowest id and the ordering matches the order they were built.

The sequence starts at 100000 so every id is six digits: a number that changes
width as the table grows looks like two different kinds of identifier.

Revision ID: 0020_chatbot_display_id
Revises: 0019_pin_assistant_knowledge
Create Date: 2026-08-10
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0020_chatbot_display_id"
down_revision: str | None = "0019_pin_assistant_knowledge"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_SEQUENCE = "chatbot_display_id_seq"


def upgrade() -> None:
    op.execute(f"CREATE SEQUENCE IF NOT EXISTS {_SEQUENCE} START WITH 100000")
    op.add_column("chatbots", sa.Column("display_id", sa.Integer(), nullable=True))

    # Oldest first, so the numbering reflects the order they were created.
    op.execute(
        f"""
        UPDATE chatbots c
        SET display_id = numbered.seq
        FROM (
            SELECT id, nextval('{_SEQUENCE}') AS seq
            FROM (SELECT id FROM chatbots ORDER BY created_at, id) ordered
        ) numbered
        WHERE c.id = numbered.id
        """
    )

    op.alter_column(
        "chatbots",
        "display_id",
        nullable=False,
        server_default=sa.text(f"nextval('{_SEQUENCE}')"),
    )
    op.create_unique_constraint("uq_chatbots_display_id", "chatbots", ["display_id"])


def downgrade() -> None:
    op.drop_constraint("uq_chatbots_display_id", "chatbots", type_="unique")
    op.drop_column("chatbots", "display_id")
    op.execute(f"DROP SEQUENCE IF EXISTS {_SEQUENCE}")
