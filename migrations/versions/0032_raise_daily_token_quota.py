"""Raise the daily token ceiling to something the booking agent can live under

200,000 tokens a day was sized for the retrieval path: a question in, an answer
out, a couple of thousand tokens a turn. The front-office booking agent is a
different shape entirely — a multi-step tool loop that re-sends the whole tool
catalogue and the running state on every step — so one booking conversation can
cost 40-50k.

At the old ceiling a workspace ran dry after roughly four bookings. What made it
hard to diagnose is how it presents: the quota is per *workspace* and per *day*,
so it does not degrade, it stops everything at once, and it clears by itself at
midnight UTC. From the outside that looks exactly like an intermittent server
fault that "fixes itself" and then comes back — which is how it was reported,
repeatedly.

Only rows still sitting on the old default are moved. A workspace whose quota
was deliberately set to something else has had that decision made about it, and
a migration must not quietly undo it.

Revision ID: 0032_raise_daily_token_quota
Revises: 0031_booking_slate
Create Date: 2026-09-03
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0032_raise_daily_token_quota"
down_revision: str | None = "0031_booking_slate"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_OLD_DEFAULT = 200_000
_NEW_DEFAULT = 2_000_000


def upgrade() -> None:
    op.execute(
        f"ALTER TABLE tenants ALTER COLUMN daily_token_quota SET DEFAULT {_NEW_DEFAULT}"
    )
    op.execute(
        "UPDATE tenants SET daily_token_quota = "
        f"{_NEW_DEFAULT} WHERE daily_token_quota = {_OLD_DEFAULT}"
    )


def downgrade() -> None:
    op.execute(
        f"ALTER TABLE tenants ALTER COLUMN daily_token_quota SET DEFAULT {_OLD_DEFAULT}"
    )
    # Symmetrical: only rows on the new default go back, so a workspace given a
    # bespoke quota after this migration keeps it.
    op.execute(
        "UPDATE tenants SET daily_token_quota = "
        f"{_OLD_DEFAULT} WHERE daily_token_quota = {_NEW_DEFAULT}"
    )
