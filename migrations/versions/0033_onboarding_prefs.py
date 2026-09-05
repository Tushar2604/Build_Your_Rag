"""Somewhere to keep what a person has already been shown

The whole of onboarding lived in one localStorage key ("onboardingState").
That meant three things, all of them wrong: a user who signed in from a second
browser got the welcome screen again as if they were new; a workspace that had
been running for months had no onboarding state at all, so it could never be
offered the parts of the product it had not set up yet; and the guided tour,
having set `tourStatus: "done"`, could never be replayed.

Only the *preferences* live here. Every milestone ("has a configured
assistant", "has ready knowledge", "has tested it", "is live on a channel") is
derived on read from the tables that already hold the answer — see
`OnboardingReadModel`. Storing a copy would let the two disagree, and the copy
would always be the one people read.

Per user rather than per tenant, and deliberately: setup progress belongs to
the workspace, but "I dismissed that card" and "I have seen this tour" belong
to the person who dismissed it. A teammate joining an established workspace
inherits its progress and none of its dismissals, which is the behaviour you
want in both halves.

Revision ID: 0033_onboarding_prefs
Revises: 0032_raise_daily_token_quota
Create Date: 2026-09-05
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision: str = "0033_onboarding_prefs"
down_revision: str | None = "0032_raise_daily_token_quota"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "onboarding_prefs",
        # The user IS the row — one set of preferences per person, so the FK
        # doubles as the primary key and there is no second id to keep unique.
        sa.Column(
            "user_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "tenant_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        # "guided" reveals the navigation in step with what the workspace has
        # actually set up; "full" is the permanent escape hatch behind the
        # rail's "Show all features". Never flipped by the app itself — only
        # by the person clicking it.
        sa.Column("nav_mode", sa.String(16), nullable=False, server_default="guided"),
        # Which tours have been played to the end, by area key. A list, not a
        # single "done" flag, because tours are now per-area and replayable —
        # this only decides whether one is *offered* unprompted.
        sa.Column(
            "tours_completed",
            pg.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        # Cards this person has closed ("welcome", "checklist", ...).
        sa.Column(
            "dismissed",
            pg.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        # Stages whose unlock has already been announced, so the "Appointments
        # just unlocked" toast fires once per person and not once per page load.
        sa.Column(
            "celebrated_stages",
            pg.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_onboarding_prefs_tenant_id", "onboarding_prefs", ["tenant_id"])

    op.execute("ALTER TABLE onboarding_prefs ENABLE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_isolation ON onboarding_prefs "
        "USING (tenant_id = current_setting('app.tenant_id', true)::uuid)"
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON onboarding_prefs")
    op.drop_index("ix_onboarding_prefs_tenant_id", table_name="onboarding_prefs")
    op.drop_table("onboarding_prefs")
