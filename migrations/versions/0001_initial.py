"""initial schema: tenants, users, documents, chunks (pgvector), chatbots, chat, usage, audit

Revision ID: 0001_initial
Revises:
Create Date: 2026-06-26
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg
from src.config import get_settings

revision: str = "0001_initial"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

EMBEDDING_DIM = get_settings().embedding_dim

# Tenant-scoped tables get an RLS policy keyed on app.tenant_id.
_RLS_TABLES = [
    "users",
    "api_keys",
    "documents",
    "document_chunks",
    "chatbots",
    "chat_sessions",
    "chat_messages",
    "usage_counters",
    "audit_events",
]


def upgrade() -> None:
    op.create_table(
        "tenants",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("slug", sa.String(64), nullable=False, unique=True),
        sa.Column("daily_token_quota", sa.Integer, nullable=False, server_default="200000"),
        sa.Column("max_documents", sa.Integer, nullable=False, server_default="200"),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "users",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", pg.UUID(as_uuid=True),
                  sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("email", sa.String(255), nullable=False, unique=True, index=True),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("role", sa.String(20), nullable=False, server_default="owner"),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "api_keys",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", pg.UUID(as_uuid=True),
                  sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("key_hash", sa.String(255), nullable=False, unique=True, index=True),
        sa.Column("prefix", sa.String(16), nullable=False),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "documents",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", pg.UUID(as_uuid=True),
                  sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("filename", sa.String(255), nullable=False),
        sa.Column("content_type", sa.String(120), nullable=False),
        sa.Column("size_bytes", sa.Integer, nullable=False),
        sa.Column("storage_key", sa.String(512), nullable=False),
        sa.Column("checksum", sa.String(128), nullable=False, server_default=""),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending", index=True),
        sa.Column("chunk_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("error", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "document_chunks",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", pg.UUID(as_uuid=True), nullable=False, index=True),
        sa.Column("document_id", pg.UUID(as_uuid=True),
                  sa.ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("ordinal", sa.Integer, nullable=False),
        sa.Column("text", sa.Text, nullable=False),
        sa.Column("token_estimate", sa.Integer, nullable=False, server_default="0"),
        sa.Column("embedding", pg.ARRAY(sa.Float), nullable=True),
    )

    op.create_table(
        "chatbots",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", pg.UUID(as_uuid=True),
                  sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("system_prompt", sa.Text, nullable=False),
        sa.Column("retrieval", pg.JSONB, nullable=False, server_default="{}"),
        sa.Column("allowed_document_ids", pg.JSONB, nullable=False, server_default="[]"),
        sa.Column("is_public", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "chat_sessions",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", pg.UUID(as_uuid=True),
                  sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("chatbot_id", pg.UUID(as_uuid=True),
                  sa.ForeignKey("chatbots.id", ondelete="CASCADE"), nullable=False),
        sa.Column("title", sa.String(255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "chat_messages",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", pg.UUID(as_uuid=True), nullable=False, index=True),
        sa.Column("session_id", pg.UUID(as_uuid=True),
                  sa.ForeignKey("chat_sessions.id", ondelete="CASCADE"),
                  nullable=False, index=True),
        sa.Column("role", sa.String(20), nullable=False),
        sa.Column("content", sa.Text, nullable=False),
        sa.Column("citations", pg.JSONB, nullable=False, server_default="[]"),
        sa.Column("tokens_used", sa.Integer, nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "usage_counters",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", pg.UUID(as_uuid=True), nullable=False, index=True),
        sa.Column("day", sa.Date, nullable=False, index=True),
        sa.Column("tokens_used", sa.Integer, nullable=False, server_default="0"),
        sa.UniqueConstraint("tenant_id", "day", name="uq_usage_tenant_day"),
    )

    op.create_table(
        "audit_events",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", pg.UUID(as_uuid=True), nullable=False, index=True),
        sa.Column("name", sa.String(80), nullable=False, index=True),
        sa.Column("payload", pg.JSONB, nullable=False, server_default="{}"),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
    )

    # --- Row-Level Security (defense-in-depth) ---
    # Policies bind isolation to the per-transaction `app.tenant_id` GUC. NOTE:
    # table owners bypass RLS, so to *enforce* this the app must connect as a
    # non-owner role (see README). Until then, explicit per-query tenant filters
    # are the active guard and these policies are dormant.
    for table in _RLS_TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY tenant_isolation ON {table} USING "
            f"(tenant_id = current_setting('app.tenant_id', true)::uuid)"
        )


def downgrade() -> None:
    for table in _RLS_TABLES:
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")
    for table in [
        "audit_events", "usage_counters", "chat_messages", "chat_sessions",
        "chatbots", "document_chunks", "documents", "api_keys", "users", "tenants",
    ]:
        op.drop_table(table)
