"""Integrations catalogue connections, issue reports, and cloned voices

Three additive tables plus one nullable column:

  * `tenant_integrations` — per-tenant credentials for a catalogue integration.
    The catalogue itself ships in code (src/domain/integration/catalogue.py), so
    `integration_id` is a plain key rather than a foreign key: adding a new
    integration is a deploy, not a migration.
  * `issue_reports` — Report Issue submissions, kept even when email delivery is
    unconfigured so nothing a user typed is ever dropped.
  * `voice_profiles` — cloned voices, plus `chatbots.voice_profile_id` so an
    assistant can speak in one. That FK is ON DELETE SET NULL: deleting a voice
    must degrade the assistant to the default voice, never delete the assistant.

Revision ID: 0015_integrations_support_voice
Revises: 0014_tighten_default_prompt
Create Date: 2026-08-08
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision: str = "0015_integrations_support_voice"
down_revision: str | None = "0014_tighten_default_prompt"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_RLS_TABLES = ("tenant_integrations", "issue_reports", "voice_profiles")


def upgrade() -> None:
    op.create_table(
        "tenant_integrations",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", pg.UUID(as_uuid=True),
                  sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("integration_id", sa.String(64), nullable=False, index=True),
        sa.Column("config", pg.JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("enabled", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        # One connection per integration per tenant — also the conflict target
        # that makes re-connecting (e.g. rotating a leaked webhook) an upsert.
        sa.UniqueConstraint("tenant_id", "integration_id", name="uq_tenant_integration"),
    )

    op.create_table(
        "issue_reports",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", pg.UUID(as_uuid=True),
                  sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column("email", sa.String(320), nullable=False),
        sa.Column("phone", sa.String(32), nullable=False, server_default=""),
        sa.Column("report_type", sa.String(32), nullable=False, index=True),
        sa.Column("priority", sa.String(16), nullable=False, server_default="medium", index=True),
        sa.Column("subject", sa.String(200), nullable=False),
        sa.Column("description", sa.Text, nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="open", index=True),
        sa.Column("page_url", sa.String(500), nullable=False, server_default=""),
        sa.Column("user_agent", sa.String(500), nullable=False, server_default=""),
        sa.Column("email_sent", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "voice_profiles",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", pg.UUID(as_uuid=True),
                  sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("name", sa.String(80), nullable=False),
        sa.Column("gender", sa.String(16), nullable=False, server_default="female"),
        sa.Column("language", sa.String(8), nullable=False, server_default="en"),
        sa.Column("description", sa.String(500), nullable=False, server_default=""),
        sa.Column("sample_storage_key", sa.String(512), nullable=False, server_default=""),
        sa.Column("sample_content_type", sa.String(120), nullable=False, server_default=""),
        sa.Column("sample_bytes", sa.Integer, nullable=False, server_default="0"),
        sa.Column("duration_seconds", sa.Float, nullable=False, server_default="0"),
        sa.Column("provider", sa.String(32), nullable=False, server_default=""),
        # Indexed: synthesis and vendor-side cleanup both look up by this.
        sa.Column("provider_voice_id", sa.String(128), nullable=False,
                  server_default="", index=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending", index=True),
        sa.Column("error", sa.Text, nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.add_column(
        "chatbots",
        sa.Column(
            "voice_profile_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("voice_profiles.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )

    for table in _RLS_TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY tenant_isolation ON {table} USING "
            "(tenant_id = current_setting('app.tenant_id', true)::uuid)"
        )


def downgrade() -> None:
    for table in _RLS_TABLES:
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")
    op.drop_column("chatbots", "voice_profile_id")
    op.drop_table("voice_profiles")
    op.drop_table("issue_reports")
    op.drop_table("tenant_integrations")
