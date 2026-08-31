"""Remember which appointments have already been reminded

The reminder sweep reads the appointments starting soon, then sends to each in
a later transaction. Without a marker on the row, a sweep that ran twice — two
web workers, or one process restarting mid-tick — would send the same customer
the same reminder again. A duplicate nudge to a real person is the one thing
this feature must never do, so the fact that we sent lives in the database
rather than in the sweep's memory.

NULL means "not reminded yet", which is also what keeps the sweep's query
cheap: the partial index below covers only the rows still awaiting one, and
that set is tiny compared to the table's history.

Deliberately a timestamp rather than a boolean. "Did we remind them, and when"
is a question the appointment detail view and any future support conversation
both want answered, and a boolean throws the second half away.

Revision ID: 0028_appointment_reminders
Revises: 0027_canonical_contact_numbers
Create Date: 2026-08-29
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0028_appointment_reminders"
down_revision: str | None = "0027_canonical_contact_numbers"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "appointments",
        sa.Column("reminder_sent_at", sa.DateTime(timezone=True), nullable=True),
    )
    # Partial, and ordered by the column the sweep actually filters on. Every
    # appointment ever booked eventually has this set; the sweep only ever asks
    # about the handful that do not.
    op.create_index(
        "ix_appointments_awaiting_reminder",
        "appointments",
        ["starts_at"],
        postgresql_where=sa.text("reminder_sent_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_appointments_awaiting_reminder", table_name="appointments")
    op.drop_column("appointments", "reminder_sent_at")
