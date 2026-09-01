"""Let a WhatsApp channel be a Meta Cloud API number, not only a Twilio one

The table was written when Twilio was the only way a business number could
reach this app, so the provider's name is in the column names. Meta's Cloud API
is a different shape entirely: it identifies a number by an opaque
`phone_number_id` rather than by the number itself, authenticates with a
long-lived access token rather than an account SID and auth token, and signs its
webhooks with the *app's* secret rather than the channel's.

Adding a `provider` discriminator alongside the existing columns, rather than a
second table, because everything downstream — conversations, the inbox, the
broadcast funnel, the assistant routing — already keys off `whatsapp_channels.id`
and should not have to learn which vendor is behind it. The send path is the
only place the difference matters, and that is one branch.

Existing rows are Twilio by definition, which is what the server default says.

`phone_number_id` is uniquely indexed only where it is set: it is how an inbound
Cloud webhook resolves to a channel (the payload carries no tenant), so two
channels sharing one would route someone else's customer into the wrong
workspace — while every Twilio row leaves it blank and must not collide.

Revision ID: 0029_whatsapp_cloud_channel
Revises: 0028_appointment_reminders
Create Date: 2026-09-01
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0029_whatsapp_cloud_channel"
down_revision: str | None = "0028_appointment_reminders"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "whatsapp_channels",
        sa.Column(
            "provider",
            sa.String(16),
            nullable=False,
            server_default="twilio",
        ),
    )
    # Meta's own id for the number. Opaque, and the only thing an inbound
    # webhook can be resolved by — the display number in the payload is
    # cosmetic and formatted inconsistently.
    op.add_column(
        "whatsapp_channels",
        sa.Column("phone_number_id", sa.String(64), nullable=False, server_default=""),
    )
    # The WhatsApp Business Account the number belongs to. Not needed to send;
    # kept because template management and quality ratings are asked of the
    # WABA, and re-finding it by hand later is a support conversation.
    op.add_column(
        "whatsapp_channels",
        sa.Column("waba_id", sa.String(64), nullable=False, server_default=""),
    )
    # A permanent System User token. Text, not String(255): Meta's tokens have
    # already grown past 200 characters once.
    op.add_column(
        "whatsapp_channels",
        sa.Column("access_token", sa.Text, nullable=False, server_default=""),
    )
    # The existing Twilio credentials are NOT NULL, and a Cloud channel has
    # none — so they need a default rather than a value invented per insert.
    op.alter_column("whatsapp_channels", "twilio_account_sid", server_default="")
    op.alter_column("whatsapp_channels", "twilio_auth_token", server_default="")

    op.create_index(
        "uq_whatsapp_channels_phone_number_id",
        "whatsapp_channels",
        ["phone_number_id"],
        unique=True,
        postgresql_where=sa.text("phone_number_id <> ''"),
    )


def downgrade() -> None:
    op.drop_index(
        "uq_whatsapp_channels_phone_number_id", table_name="whatsapp_channels"
    )
    op.alter_column("whatsapp_channels", "twilio_auth_token", server_default=None)
    op.alter_column("whatsapp_channels", "twilio_account_sid", server_default=None)
    op.drop_column("whatsapp_channels", "access_token")
    op.drop_column("whatsapp_channels", "waba_id")
    op.drop_column("whatsapp_channels", "phone_number_id")
    op.drop_column("whatsapp_channels", "provider")
