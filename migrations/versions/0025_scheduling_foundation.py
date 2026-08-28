"""Scheduling foundation: locations, services, resources, availability, appointments

The appointment engine's schema. Additive only — nothing existing is altered, and
in particular `interviews` and `interview_batches` are untouched: they are a
working feature with their own lifecycle, and folding them into appointments is a
migration to make deliberately later, not a side effect of adding a scheduler.

The design decision worth reading is `resource_reservations`.

Two customers can ask for 3:00 PM in the same instant — over the phone, in a
widget, from a WhatsApp thread — and only one of them can have it. Checking
availability and then inserting cannot be made safe in application code: between
the check and the write there is always a window, and `SELECT ... FOR UPDATE`
cannot lock a row that does not exist yet. Serializing every booking through one
lock would be correct and unusably slow.

So the guarantee lives in Postgres. Holds and bookings are rows in ONE table,
and a GiST exclusion constraint forbids two live rows for the same resource whose
time ranges overlap:

    EXCLUDE USING gist (
        resource_id WITH =,
        (tstzrange(starts_at, ends_at, '[)')) WITH &&
    ) WHERE (released_at IS NULL)

Whoever commits second gets a constraint violation, which the booking use case
turns into a 409 and a fresh slot list. No lock ordering, no retry loop, no
dependence on how many web workers are running. `btree_gist` is required because
the equality operator on a uuid is a btree operator, and the constraint mixes it
with a GiST range overlap in one index.

The range is an EXPRESSION over two ordinary timestamptz columns rather than a
stored range column, so the ORM writes plain datetimes and no driver-specific
range type is ever involved.

`released_at` rather than deleting a row: a cancelled booking keeps its record of
what was held while dropping out of the constraint's scope, which is what lets a
cancelled slot be rebooked without losing the history that it once was not.

Revision ID: 0025_scheduling_foundation
Revises: 0024_conversation_follow_ups
Create Date: 2026-08-28
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision: str = "0025_scheduling_foundation"
down_revision: str | None = "0024_conversation_follow_ups"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Every one of these is tenant-scoped, so every one gets the same RLS policy the
# rest of the schema uses.
_RLS_TABLES = [
    "locations",
    "services",
    "resources",
    "service_resources",
    "availability_rules",
    "blocked_periods",
    "appointments",
    "appointment_status_history",
    "resource_reservations",
]


def upgrade() -> None:
    # Required by the exclusion constraint below: it combines btree equality on
    # a uuid with GiST range overlap in a single index, which core Postgres
    # cannot do without this extension.
    op.execute("CREATE EXTENSION IF NOT EXISTS btree_gist")

    # --- Configuration: where, what, and who -------------------------------
    op.create_table(
        "locations",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column("slug", sa.String(80), nullable=False),
        # IANA name, never an offset: an offset is wrong for half the year
        # anywhere that observes daylight saving.
        sa.Column("timezone", sa.String(64), nullable=False, server_default="UTC"),
        sa.Column("address", sa.Text, nullable=False, server_default=""),
        sa.Column("phone", sa.String(32), nullable=False, server_default=""),
        sa.Column("email", sa.String(320), nullable=False, server_default=""),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("tenant_id", "slug", name="uq_location_tenant_slug"),
    )
    op.create_index("ix_locations_tenant_id", "locations", ["tenant_id"])

    op.create_table(
        "services",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column("category", sa.String(160), nullable=False, server_default=""),
        sa.Column("description", sa.Text, nullable=False, server_default=""),
        sa.Column("duration_minutes", sa.Integer, nullable=False),
        sa.Column("buffer_before_minutes", sa.Integer, nullable=False, server_default="0"),
        sa.Column("buffer_after_minutes", sa.Integer, nullable=False, server_default="0"),
        # Minor units. Never a float: a rounded price is a support ticket.
        sa.Column("price_cents", sa.Integer, nullable=False, server_default="0"),
        sa.Column("deposit_cents", sa.Integer, nullable=False, server_default="0"),
        sa.Column("currency", sa.String(3), nullable=False, server_default="AED"),
        sa.Column("min_notice_minutes", sa.Integer, nullable=False, server_default="0"),
        sa.Column("max_horizon_days", sa.Integer, nullable=False, server_default="60"),
        sa.Column(
            "cancellation_window_hours", sa.Integer, nullable=False, server_default="0"
        ),
        sa.Column(
            "online_bookable", sa.Boolean, nullable=False, server_default=sa.true()
        ),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_services_tenant_id", "services", ["tenant_id"])
    # The service picker only ever asks for live services.
    op.create_index("ix_services_tenant_active", "services", ["tenant_id", "is_active"])

    op.create_table(
        "resources",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column("kind", sa.String(20), nullable=False, server_default="staff"),
        # SET NULL both ways: closing a branch must not delete the doctors who
        # worked there, and removing a login must not delete the resource that
        # existing appointments point at.
        sa.Column(
            "location_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("locations.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "user_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("email", sa.String(320), nullable=False, server_default=""),
        sa.Column("phone", sa.String(32), nullable=False, server_default=""),
        sa.Column("capacity", sa.Integer, nullable=False, server_default="1"),
        sa.Column("timezone", sa.String(64), nullable=False, server_default=""),
        sa.Column("color", sa.String(16), nullable=False, server_default=""),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_resources_tenant_id", "resources", ["tenant_id"])
    op.create_index("ix_resources_kind", "resources", ["kind"])

    op.create_table(
        "service_resources",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "service_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("services.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "resource_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("resources.id", ondelete="CASCADE"),
            nullable=False,
        ),
        # The role is what makes "a dentist AND a chair" expressible.
        sa.Column("role", sa.String(40), nullable=False, server_default="primary"),
        sa.Column("required", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "service_id", "resource_id", "role", name="uq_service_resource_role"
        ),
    )
    op.create_index("ix_service_resources_tenant_id", "service_resources", ["tenant_id"])
    op.create_index("ix_service_resources_service_id", "service_resources", ["service_id"])
    op.create_index(
        "ix_service_resources_resource_id", "service_resources", ["resource_id"]
    )

    # --- When: recurring openness, and absolute closures --------------------
    op.create_table(
        "availability_rules",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("owner_kind", sa.String(16), nullable=False),
        sa.Column("owner_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("weekday", sa.Integer, nullable=False),
        # `Time` WITHOUT a zone, deliberately. These are wall-clock: "Mondays
        # 09:00" must stay 09:00 across a daylight-saving change, and a stored
        # UTC instant would move every branch by an hour twice a year. The zone
        # comes from the owning location at query time.
        sa.Column("start_time", sa.Time, nullable=False),
        sa.Column("end_time", sa.Time, nullable=False),
        sa.Column("effective_from", sa.DateTime(timezone=True), nullable=True),
        sa.Column("effective_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_availability_rules_tenant_id", "availability_rules", ["tenant_id"])
    # The engine's hot path: every rule for one owner, for one query.
    op.create_index(
        "ix_availability_rules_owner",
        "availability_rules",
        ["tenant_id", "owner_kind", "owner_id", "weekday"],
    )

    op.create_table(
        "blocked_periods",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("owner_kind", sa.String(16), nullable=False),
        sa.Column("owner_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reason", sa.String(300), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_blocked_periods_tenant_id", "blocked_periods", ["tenant_id"])
    op.create_index(
        "ix_blocked_periods_owner_range",
        "blocked_periods",
        ["tenant_id", "owner_id", "starts_at", "ends_at"],
    )

    # --- The appointment itself ---------------------------------------------
    op.create_table(
        "appointments",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        # RESTRICT: deleting a branch or a service must not silently erase the
        # appointments booked against it. The UI deactivates instead.
        sa.Column(
            "location_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("locations.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "service_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("services.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("customer_name", sa.String(160), nullable=False),
        sa.Column("customer_phone", sa.String(32), nullable=False, server_default=""),
        sa.Column("customer_email", sa.String(320), nullable=False, server_default=""),
        sa.Column("customer_timezone", sa.String(64), nullable=False, server_default=""),
        sa.Column("timezone", sa.String(64), nullable=False, server_default="UTC"),
        sa.Column("status", sa.String(24), nullable=False, server_default="pending"),
        sa.Column("source", sa.String(20), nullable=False, server_default="staff"),
        sa.Column(
            "resource_ids",
            pg.JSONB,
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("customer_notes", sa.Text, nullable=False, server_default=""),
        sa.Column("internal_notes", sa.Text, nullable=False, server_default=""),
        sa.Column(
            "rescheduled_from_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("appointments.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("cancellation_reason", sa.String(500), nullable=False, server_default=""),
        sa.Column("idempotency_key", sa.String(128), nullable=False, server_default=""),
        sa.Column(
            "created_by",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_appointments_tenant_id", "appointments", ["tenant_id"])
    op.create_index("ix_appointments_starts_at", "appointments", ["starts_at"])
    op.create_index("ix_appointments_status", "appointments", ["status"])
    op.create_index("ix_appointments_source", "appointments", ["source"])
    op.create_index("ix_appointments_location_id", "appointments", ["location_id"])
    op.create_index("ix_appointments_service_id", "appointments", ["service_id"])
    op.create_index("ix_appointments_customer_phone", "appointments", ["customer_phone"])
    # The calendar's query: one tenant, one day, ordered. Covers the list view's
    # status filter too.
    op.create_index(
        "ix_appointments_tenant_window", "appointments", ["tenant_id", "starts_at"]
    )
    op.create_index(
        "ix_appointments_tenant_status_window",
        "appointments",
        ["tenant_id", "status", "starts_at"],
    )
    # Partial: a retried POST carrying the same key cannot create a second
    # booking, while the many appointments booked without a key never collide
    # with each other on an empty string.
    op.execute(
        "CREATE UNIQUE INDEX uq_appointments_idempotency_key "
        "ON appointments (tenant_id, idempotency_key) "
        "WHERE idempotency_key <> ''"
    )

    op.create_table(
        "appointment_status_history",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "appointment_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("appointments.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("from_status", sa.String(24), nullable=False),
        sa.Column("to_status", sa.String(24), nullable=False),
        sa.Column("actor_kind", sa.String(16), nullable=False),
        sa.Column("actor_id", pg.UUID(as_uuid=True), nullable=True),
        sa.Column("actor_label", sa.String(160), nullable=False, server_default=""),
        sa.Column("channel", sa.String(32), nullable=False, server_default=""),
        sa.Column("reason", sa.String(500), nullable=False, server_default=""),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_appointment_status_history_tenant_id",
        "appointment_status_history",
        ["tenant_id"],
    )
    op.create_index(
        "ix_appointment_status_history_appointment_id",
        "appointment_status_history",
        ["appointment_id"],
    )
    op.create_index(
        "ix_appointment_status_history_occurred_at",
        "appointment_status_history",
        ["occurred_at"],
    )
    # The detail drawer's timeline, in one indexed read.
    op.create_index(
        "ix_appointment_status_history_timeline",
        "appointment_status_history",
        ["appointment_id", "occurred_at"],
    )

    # --- The double-booking guard -------------------------------------------
    op.create_table(
        "resource_reservations",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "resource_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("resources.id", ondelete="CASCADE"),
            nullable=False,
        ),
        # Buffers included: this is the calendar actually consumed, which is
        # wider than the appointment the customer is shown.
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("kind", sa.String(10), nullable=False),
        sa.Column(
            "appointment_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("appointments.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("hold_token", sa.String(64), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("released_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_resource_reservations_tenant_id", "resource_reservations", ["tenant_id"]
    )
    op.create_index(
        "ix_resource_reservations_resource_id", "resource_reservations", ["resource_id"]
    )
    op.create_index("ix_resource_reservations_kind", "resource_reservations", ["kind"])
    op.create_index(
        "ix_resource_reservations_hold_token", "resource_reservations", ["hold_token"]
    )
    # The availability engine's busy-time lookup: live reservations for a set of
    # resources within a window.
    op.create_index(
        "ix_resource_reservations_lookup",
        "resource_reservations",
        ["tenant_id", "resource_id", "starts_at", "ends_at"],
        postgresql_where=sa.text("released_at IS NULL"),
    )
    # Lets the expiry sweep find only the holds that are actually due, rather
    # than scanning every reservation ever made.
    op.create_index(
        "ix_resource_reservations_expiring",
        "resource_reservations",
        ["expires_at"],
        postgresql_where=sa.text("released_at IS NULL AND kind = 'hold'"),
    )

    # THE constraint. See this module's docstring for why it exists and why it
    # is not application code.
    op.execute(
        """
        ALTER TABLE resource_reservations
        ADD CONSTRAINT no_overlapping_reservations
        EXCLUDE USING gist (
            resource_id WITH =,
            (tstzrange(starts_at, ends_at, '[)')) WITH &&
        ) WHERE (released_at IS NULL)
        """
    )
    # Half-open '[)' is what makes an appointment ending at 3pm and one starting
    # at 3pm not a conflict — matching the domain engine's `Interval.overlaps`.

    # --- Tenant isolation ----------------------------------------------------
    for table in _RLS_TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY tenant_isolation ON {table} "
            "USING (tenant_id = current_setting('app.tenant_id', true)::uuid)"
        )


def downgrade() -> None:
    for table in reversed(_RLS_TABLES):
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")
    # Dropped in dependency order. `btree_gist` is deliberately left installed:
    # it is shared infrastructure and another feature may already rely on it.
    op.drop_table("resource_reservations")
    op.drop_table("appointment_status_history")
    op.drop_table("appointments")
    op.drop_table("blocked_periods")
    op.drop_table("availability_rules")
    op.drop_table("service_resources")
    op.drop_table("resources")
    op.drop_table("services")
    op.drop_table("locations")
