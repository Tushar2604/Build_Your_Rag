"""Conversational flow sections + post-call delivery

Two additive changes:

  * `chatbots.flow_sections` — the authored, section-by-section form of the
    system prompt. Backfilled to `[]`, which the mapper reads as "this bot was
    authored as a raw prompt"; the UI offers to split it into the stock sections
    on first edit. Existing `system_prompt` values are untouched, so no bot
    changes behaviour on deploy.
  * `post_call_configs` / `post_call_deliveries` — delivery rules per chatbot,
    and the audit trail of what each dispatch actually sent.

Revision ID: 0012_flow_and_post_call
Revises: 0011_team_and_custom_questions
Create Date: 2026-08-07
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision: str = "0012_flow_and_post_call"
down_revision: str | None = "0011_team_and_custom_questions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "chatbots",
        sa.Column(
            "flow_sections",
            pg.JSONB,
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )

    op.create_table(
        "post_call_configs",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", pg.UUID(as_uuid=True),
                  sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("chatbot_id", pg.UUID(as_uuid=True),
                  sa.ForeignKey("chatbots.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("delivery_method", sa.String(20), nullable=False, server_default="webhook"),
        sa.Column("webhook_url", sa.Text, nullable=False, server_default=""),
        sa.Column("email_to", sa.String(320), nullable=False, server_default=""),
        sa.Column("trigger_statuses", pg.JSONB, nullable=False,
                  server_default=sa.text("'[\"completed\"]'::jsonb")),
        sa.Column("include_summary", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("include_transcript", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("include_sentiment", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("include_extracted", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("enabled", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "post_call_deliveries",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", pg.UUID(as_uuid=True),
                  sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("chatbot_id", pg.UUID(as_uuid=True),
                  sa.ForeignKey("chatbots.id", ondelete="CASCADE"), nullable=False, index=True),
        # No FK to post_call_configs: the audit trail must survive the operator
        # deleting the rule it was sent under.
        sa.Column("config_id", pg.UUID(as_uuid=True), nullable=False, index=True),
        sa.Column("session_id", pg.UUID(as_uuid=True), nullable=False, index=True),
        sa.Column("call_status", sa.String(20), nullable=False),
        sa.Column("delivery_method", sa.String(20), nullable=False),
        sa.Column("destination", sa.Text, nullable=False, server_default=""),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("error", sa.Text, nullable=False, server_default=""),
        sa.Column("payload", pg.JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    # The dedupe guard: one delivery per (config, session) — a retried sweep or
    # a double "end session" call must not double-post to a customer's ATS.
    op.create_unique_constraint(
        "uq_post_call_delivery_config_session",
        "post_call_deliveries",
        ["config_id", "session_id"],
    )

    for table in ("post_call_configs", "post_call_deliveries"):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY tenant_isolation ON {table} USING "
            "(tenant_id = current_setting('app.tenant_id', true)::uuid)"
        )


def downgrade() -> None:
    for table in ("post_call_deliveries", "post_call_configs"):
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")
    op.drop_constraint(
        "uq_post_call_delivery_config_session", "post_call_deliveries", type_="unique"
    )
    op.drop_table("post_call_deliveries")
    op.drop_table("post_call_configs")
    op.drop_column("chatbots", "flow_sections")
