"""Generic per-provider OAuth connections

Replaces `google_oauth_connections` (one table, one vendor) with
`oauth_connections` keyed (tenant_id, provider). Google Calendar was the only
OAuth integration when that table was written; Google Sheets and Cal.com connect
the same way, and a table per vendor would mean a migration per integration.

Existing Google Calendar connections are carried across rather than dropped —
they represent consent a user already gave, and losing them would silently break
interview scheduling until every tenant reconnected.

Revision ID: 0018_oauth_connections
Revises: 0017_assistant_config
Create Date: 2026-08-10
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision: str = "0018_oauth_connections"
down_revision: str | None = "0017_assistant_config"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "oauth_connections",
        sa.Column(
            "tenant_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        # Matches an id in infrastructure/oauth/providers.PROVIDER_SPECS.
        sa.Column("provider", sa.String(64), primary_key=True),
        sa.Column("access_token", sa.Text, nullable=False),
        # Empty when the vendor issued none (some only do so on first consent).
        # The connection still works until the access token expires.
        sa.Column("refresh_token", sa.Text, nullable=False, server_default=""),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("scope", sa.String(1000), nullable=False, server_default=""),
        # "Connected as …" — an email or account name, purely for display.
        sa.Column("account_label", sa.String(320), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
    )

    op.execute(
        """
        INSERT INTO oauth_connections
            (tenant_id, provider, access_token, refresh_token, expires_at,
             scope, account_label, created_at, updated_at)
        SELECT tenant_id, 'google_calendar', access_token, refresh_token,
               expires_at, LEFT(scope, 1000), connected_email, created_at, updated_at
        FROM google_oauth_connections
        """
    )
    op.drop_table("google_oauth_connections")

    op.execute("ALTER TABLE oauth_connections ENABLE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_isolation ON oauth_connections USING "
        "(tenant_id = current_setting('app.tenant_id', true)::uuid)"
    )


def downgrade() -> None:
    op.create_table(
        "google_oauth_connections",
        sa.Column(
            "tenant_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("access_token", sa.Text, nullable=False),
        sa.Column("refresh_token", sa.Text, nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("scope", sa.String(500), nullable=False, server_default=""),
        sa.Column("connected_email", sa.String(320), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
    )
    op.execute(
        """
        INSERT INTO google_oauth_connections
            (tenant_id, access_token, refresh_token, expires_at, scope,
             connected_email, created_at, updated_at)
        SELECT tenant_id, access_token, refresh_token, expires_at,
               LEFT(scope, 500), account_label, created_at, updated_at
        FROM oauth_connections WHERE provider = 'google_calendar'
        """
    )
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON oauth_connections")
    op.drop_table("oauth_connections")
