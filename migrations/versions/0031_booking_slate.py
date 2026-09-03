"""Give a booking conversation somewhere to remember what it already knows

The receptionist agent could list real availability and could book — but not in
the same conversation. Each inbound message starts a fresh agent run whose only
memory is the rendered chat transcript, and a transcript records what was
*said*, not the service id, the branch id, or the exact instant behind
"Thu 03 Sep, 9:00 AM".

So every turn re-derived those by calling `find_available_slots` again, and that
tool exists to produce a numbered list to read out — so the agent read it out
again. Reported from a live WhatsApp thread: four times offered, "2" chosen,
the same four times offered back; name given, phone given, reason given, and
still the list came back. It could not book, because by then it no longer knew
which slot the "2" had meant.

`chat_sessions.booking_state` is the missing memory. One nullable JSONB column
holding the slate (`src/domain/scheduling/slate.py`): the options as offered
with their `starts_at`, which one was chosen, the live hold token, and the
details the customer has already given. On the session rather than in a table of
its own because its lifetime is exactly the session's — one row, read on every
inbound message, removed by the same cascade.

Nullable with no backfill: an absent slate is an empty slate, which is precisely
how conversations already in flight behaved before this existed.

Revision ID: 0031_booking_slate
Revises: 0030_flow_asks_name_first
Create Date: 2026-09-02
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision: str = "0031_booking_slate"
down_revision: str | None = "0030_flow_asks_name_first"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "chat_sessions",
        sa.Column("booking_state", pg.JSONB(astext_type=sa.Text()), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("chat_sessions", "booking_state")
