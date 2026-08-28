"""SQLAlchemy repositories for the scheduling module, plus their mappers.

Its own module rather than more of `repositories.py` (already 2200 lines) and
`mappers.py`: this is a self-contained bounded context, and keeping its queries
and its ORM translation together makes the double-booking guard readable in one
place. The conventions are identical to the older module — every query filters
`tenant_id` explicitly, with Postgres RLS as the backstop.

The part worth reading is `ReservationRepositoryImpl`: it is where the exclusion
constraint added by migration 0025 is turned into a domain-level conflict.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, cast

from sqlalchemy import CursorResult, Result, delete, func, or_, select, update
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.ports.repositories import HeldReservation
from src.domain.scheduling.availability import Interval
from src.domain.scheduling.entities import (
    Appointment,
    AvailabilityRule,
    BlockedPeriod,
    Location,
    Resource,
    Service,
    ServiceResource,
    StatusChange,
)
from src.domain.shared.errors import ConflictError
from src.domain.shared.identifiers import (
    AppointmentId,
    AvailabilityRuleId,
    BlockedPeriodId,
    LocationId,
    ResourceId,
    ServiceId,
    TenantId,
    UserId,
)
from src.infrastructure.persistence import models as m


# The constraint name from migration 0025. Matched against the driver's error
# text to tell "this slot just went" apart from any other integrity failure —
# they are a 409 and a 500 respectively, and conflating them would report a real
# bug to the customer as "please pick another time".
def _rowcount(result: Result[Any]) -> int:
    """How many rows an UPDATE or DELETE actually touched.

    `AsyncSession.execute` is typed as returning `Result`, which does not declare
    `rowcount` — a DML statement really returns a `CursorResult`, which does. One
    cast here rather than a type-ignore at every call site.
    """
    return int(cast("CursorResult[Any]", result).rowcount or 0)


OVERLAP_CONSTRAINT = "no_overlapping_reservations"
IDEMPOTENCY_CONSTRAINT = "uq_appointments_idempotency_key"

# SQLSTATEs that all mean the same thing to a customer: somebody else got the
# slot first.
#
#   23P01 exclusion_violation   — the common case. The other booking had already
#                                 committed, so Postgres rejects this one.
#   40P01 deadlock_detected     — the genuinely simultaneous case, and the one a
#                                 hermetic test can never find. Checking an
#                                 exclusion constraint takes a ShareLock on the
#                                 conflicting transaction to see whether it
#                                 commits; when two racers each hold a row the
#                                 other is waiting on, Postgres breaks the tie by
#                                 killing one. Exactly one booking still
#                                 survives — but the loser arrives here as a
#                                 deadlock rather than a constraint violation,
#                                 and without this it would surface as a 500
#                                 instead of "please pick another time".
#   40001 serialization_failure — the same situation under a stricter isolation
#                                 level, included so raising isolation later
#                                 cannot silently reintroduce the 500.
_CONFLICT_SQLSTATES = frozenset({"23P01", "40P01", "40001"})


def _is_slot_conflict(exc: DBAPIError) -> bool:
    """True when this error means "that time just went", not "something broke"."""
    sqlstate = getattr(exc.orig, "sqlstate", None) or getattr(exc, "code", None)
    if sqlstate in _CONFLICT_SQLSTATES:
        return True
    # Older drivers do not always expose a sqlstate on the wrapped exception;
    # the constraint name in the message is an unambiguous fallback.
    return OVERLAP_CONSTRAINT in str(exc.orig)


# --- Mappers ----------------------------------------------------------------


def location_to_domain(row: m.LocationModel) -> Location:
    return Location(
        id=LocationId(row.id),
        tenant_id=TenantId(row.tenant_id),
        name=row.name,
        timezone=row.timezone,
        address=row.address,
        phone=row.phone,
        email=row.email,
        is_active=row.is_active,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def service_to_domain(row: m.ServiceModel) -> Service:
    return Service(
        id=ServiceId(row.id),
        tenant_id=TenantId(row.tenant_id),
        name=row.name,
        category=row.category,
        description=row.description,
        duration_minutes=row.duration_minutes,
        buffer_before_minutes=row.buffer_before_minutes,
        buffer_after_minutes=row.buffer_after_minutes,
        price_cents=row.price_cents,
        deposit_cents=row.deposit_cents,
        currency=row.currency,
        min_notice_minutes=row.min_notice_minutes,
        max_horizon_days=row.max_horizon_days,
        cancellation_window_hours=row.cancellation_window_hours,
        online_bookable=row.online_bookable,
        is_active=row.is_active,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def resource_to_domain(row: m.ResourceModel) -> Resource:
    return Resource(
        id=ResourceId(row.id),
        tenant_id=TenantId(row.tenant_id),
        name=row.name,
        kind=row.kind,  # type: ignore[arg-type]
        location_id=LocationId(row.location_id) if row.location_id else None,
        user_id=UserId(row.user_id) if row.user_id else None,
        email=row.email,
        phone=row.phone,
        capacity=row.capacity,
        timezone=row.timezone,
        color=row.color,
        is_active=row.is_active,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def rule_to_domain(row: m.AvailabilityRuleModel) -> AvailabilityRule:
    return AvailabilityRule(
        id=AvailabilityRuleId(row.id),
        tenant_id=TenantId(row.tenant_id),
        owner_kind=row.owner_kind,  # type: ignore[arg-type]
        owner_id=row.owner_id,
        weekday=row.weekday,
        start_time=row.start_time,
        end_time=row.end_time,
        effective_from=row.effective_from,
        effective_until=row.effective_until,
        is_active=row.is_active,
        created_at=row.created_at,
    )


def block_to_domain(row: m.BlockedPeriodModel) -> BlockedPeriod:
    return BlockedPeriod(
        id=BlockedPeriodId(row.id),
        tenant_id=TenantId(row.tenant_id),
        owner_kind=row.owner_kind,  # type: ignore[arg-type]
        owner_id=row.owner_id,
        starts_at=row.starts_at,
        ends_at=row.ends_at,
        reason=row.reason,
        created_at=row.created_at,
    )


def appointment_to_domain(row: m.AppointmentModel) -> Appointment:
    return Appointment(
        id=AppointmentId(row.id),
        tenant_id=TenantId(row.tenant_id),
        location_id=LocationId(row.location_id),
        service_id=ServiceId(row.service_id),
        starts_at=row.starts_at,
        ends_at=row.ends_at,
        customer_name=row.customer_name,
        customer_phone=row.customer_phone,
        customer_email=row.customer_email,
        customer_timezone=row.customer_timezone,
        timezone=row.timezone,
        status=row.status,  # type: ignore[arg-type]
        source=row.source,  # type: ignore[arg-type]
        resource_ids=[ResourceId(uuid.UUID(r)) for r in (row.resource_ids or [])],
        customer_notes=row.customer_notes,
        internal_notes=row.internal_notes,
        rescheduled_from_id=(
            AppointmentId(row.rescheduled_from_id) if row.rescheduled_from_id else None
        ),
        cancellation_reason=row.cancellation_reason,
        idempotency_key=row.idempotency_key,
        created_by=UserId(row.created_by) if row.created_by else None,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def status_change_to_domain(row: m.AppointmentStatusHistoryModel) -> StatusChange:
    return StatusChange(
        id=row.id,
        tenant_id=TenantId(row.tenant_id),
        appointment_id=AppointmentId(row.appointment_id),
        from_status=row.from_status,
        to_status=row.to_status,
        actor_kind=row.actor_kind,  # type: ignore[arg-type]
        actor_id=row.actor_id,
        actor_label=row.actor_label,
        channel=row.channel,
        reason=row.reason,
        occurred_at=row.occurred_at,
    )


def _slugify(name: str) -> str:
    """A URL-safe handle for a location, unique per tenant (enforced by the DB)."""
    cleaned = "".join(c if c.isalnum() else "-" for c in name.lower())
    return "-".join(part for part in cleaned.split("-") if part)[:80] or "location"


# --- Repositories -----------------------------------------------------------


class LocationRepositoryImpl:
    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    async def add(self, location: Location) -> None:
        self._s.add(
            m.LocationModel(
                id=location.id,
                tenant_id=location.tenant_id,
                name=location.name,
                slug=_slugify(location.name),
                timezone=location.timezone,
                address=location.address,
                phone=location.phone,
                email=location.email,
                is_active=location.is_active,
                created_at=location.created_at,
                updated_at=location.updated_at,
            )
        )

    async def get(self, tenant_id: TenantId, location_id: LocationId) -> Location | None:
        row = (
            await self._s.execute(
                select(m.LocationModel).where(
                    m.LocationModel.tenant_id == tenant_id,
                    m.LocationModel.id == location_id,
                )
            )
        ).scalar_one_or_none()
        return location_to_domain(row) if row else None

    async def list_for_tenant(
        self, tenant_id: TenantId, *, active_only: bool = False
    ) -> list[Location]:
        stmt = select(m.LocationModel).where(m.LocationModel.tenant_id == tenant_id)
        if active_only:
            stmt = stmt.where(m.LocationModel.is_active.is_(True))
        rows = (await self._s.execute(stmt.order_by(m.LocationModel.name))).scalars().all()
        return [location_to_domain(r) for r in rows]

    async def update(self, location: Location) -> None:
        await self._s.execute(
            update(m.LocationModel)
            .where(
                m.LocationModel.tenant_id == location.tenant_id,
                m.LocationModel.id == location.id,
            )
            .values(
                name=location.name,
                timezone=location.timezone,
                address=location.address,
                phone=location.phone,
                email=location.email,
                is_active=location.is_active,
                updated_at=location.updated_at,
            )
        )


class ServiceRepositoryImpl:
    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    async def add(self, service: Service) -> None:
        self._s.add(
            m.ServiceModel(
                id=service.id,
                tenant_id=service.tenant_id,
                name=service.name,
                category=service.category,
                description=service.description,
                duration_minutes=service.duration_minutes,
                buffer_before_minutes=service.buffer_before_minutes,
                buffer_after_minutes=service.buffer_after_minutes,
                price_cents=service.price_cents,
                deposit_cents=service.deposit_cents,
                currency=service.currency,
                min_notice_minutes=service.min_notice_minutes,
                max_horizon_days=service.max_horizon_days,
                cancellation_window_hours=service.cancellation_window_hours,
                online_bookable=service.online_bookable,
                is_active=service.is_active,
                created_at=service.created_at,
                updated_at=service.updated_at,
            )
        )

    async def get(self, tenant_id: TenantId, service_id: ServiceId) -> Service | None:
        row = (
            await self._s.execute(
                select(m.ServiceModel).where(
                    m.ServiceModel.tenant_id == tenant_id,
                    m.ServiceModel.id == service_id,
                )
            )
        ).scalar_one_or_none()
        return service_to_domain(row) if row else None

    async def list_for_tenant(
        self, tenant_id: TenantId, *, active_only: bool = False
    ) -> list[Service]:
        stmt = select(m.ServiceModel).where(m.ServiceModel.tenant_id == tenant_id)
        if active_only:
            stmt = stmt.where(m.ServiceModel.is_active.is_(True))
        rows = (
            await self._s.execute(
                stmt.order_by(m.ServiceModel.category, m.ServiceModel.name)
            )
        ).scalars().all()
        return [service_to_domain(r) for r in rows]

    async def update(self, service: Service) -> None:
        await self._s.execute(
            update(m.ServiceModel)
            .where(
                m.ServiceModel.tenant_id == service.tenant_id,
                m.ServiceModel.id == service.id,
            )
            .values(
                name=service.name,
                category=service.category,
                description=service.description,
                duration_minutes=service.duration_minutes,
                buffer_before_minutes=service.buffer_before_minutes,
                buffer_after_minutes=service.buffer_after_minutes,
                price_cents=service.price_cents,
                deposit_cents=service.deposit_cents,
                currency=service.currency,
                min_notice_minutes=service.min_notice_minutes,
                max_horizon_days=service.max_horizon_days,
                cancellation_window_hours=service.cancellation_window_hours,
                online_bookable=service.online_bookable,
                is_active=service.is_active,
                updated_at=service.updated_at,
            )
        )

    async def set_eligibility(
        self, tenant_id: TenantId, service_id: ServiceId, links: list[ServiceResource]
    ) -> None:
        """Replace this service's resource eligibility wholesale.

        Replace rather than merge: the editor sends the complete intended set,
        and diffing it here would silently keep a resource the user removed.
        """
        await self._s.execute(
            delete(m.ServiceResourceModel).where(
                m.ServiceResourceModel.tenant_id == tenant_id,
                m.ServiceResourceModel.service_id == service_id,
            )
        )
        for link in links:
            self._s.add(
                m.ServiceResourceModel(
                    id=link.id,
                    tenant_id=link.tenant_id,
                    service_id=link.service_id,
                    resource_id=link.resource_id,
                    role=link.role,
                    required=link.required,
                )
            )

    async def eligibility_for(
        self, tenant_id: TenantId, service_id: ServiceId
    ) -> list[ServiceResource]:
        rows = (
            await self._s.execute(
                select(m.ServiceResourceModel).where(
                    m.ServiceResourceModel.tenant_id == tenant_id,
                    m.ServiceResourceModel.service_id == service_id,
                )
            )
        ).scalars().all()
        return [
            ServiceResource(
                id=r.id,
                tenant_id=TenantId(r.tenant_id),
                service_id=ServiceId(r.service_id),
                resource_id=ResourceId(r.resource_id),
                role=r.role,
                required=r.required,
            )
            for r in rows
        ]


class ResourceRepositoryImpl:
    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    async def add(self, resource: Resource) -> None:
        self._s.add(
            m.ResourceModel(
                id=resource.id,
                tenant_id=resource.tenant_id,
                name=resource.name,
                kind=resource.kind,
                location_id=resource.location_id,
                user_id=resource.user_id,
                email=resource.email,
                phone=resource.phone,
                capacity=resource.capacity,
                timezone=resource.timezone,
                color=resource.color,
                is_active=resource.is_active,
                created_at=resource.created_at,
                updated_at=resource.updated_at,
            )
        )

    async def get(self, tenant_id: TenantId, resource_id: ResourceId) -> Resource | None:
        row = (
            await self._s.execute(
                select(m.ResourceModel).where(
                    m.ResourceModel.tenant_id == tenant_id,
                    m.ResourceModel.id == resource_id,
                )
            )
        ).scalar_one_or_none()
        return resource_to_domain(row) if row else None

    async def list_for_tenant(
        self,
        tenant_id: TenantId,
        *,
        location_id: LocationId | None = None,
        kind: str = "",
        active_only: bool = False,
    ) -> list[Resource]:
        stmt = select(m.ResourceModel).where(m.ResourceModel.tenant_id == tenant_id)
        if location_id is not None:
            # A resource with no location belongs to every branch (a travelling
            # consultant, a shared piece of equipment), so it is included here.
            stmt = stmt.where(
                or_(
                    m.ResourceModel.location_id == location_id,
                    m.ResourceModel.location_id.is_(None),
                )
            )
        if kind:
            stmt = stmt.where(m.ResourceModel.kind == kind)
        if active_only:
            stmt = stmt.where(m.ResourceModel.is_active.is_(True))
        rows = (await self._s.execute(stmt.order_by(m.ResourceModel.name))).scalars().all()
        return [resource_to_domain(r) for r in rows]

    async def list_by_ids(
        self, tenant_id: TenantId, ids: list[ResourceId]
    ) -> list[Resource]:
        if not ids:
            return []
        rows = (
            await self._s.execute(
                select(m.ResourceModel).where(
                    m.ResourceModel.tenant_id == tenant_id,
                    m.ResourceModel.id.in_(ids),
                )
            )
        ).scalars().all()
        return [resource_to_domain(r) for r in rows]

    async def update(self, resource: Resource) -> None:
        await self._s.execute(
            update(m.ResourceModel)
            .where(
                m.ResourceModel.tenant_id == resource.tenant_id,
                m.ResourceModel.id == resource.id,
            )
            .values(
                name=resource.name,
                kind=resource.kind,
                location_id=resource.location_id,
                user_id=resource.user_id,
                email=resource.email,
                phone=resource.phone,
                capacity=resource.capacity,
                timezone=resource.timezone,
                color=resource.color,
                is_active=resource.is_active,
                updated_at=resource.updated_at,
            )
        )


class AvailabilityRepositoryImpl:
    """Weekly rules and absolute blocks, for locations and resources alike."""

    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    async def add_rule(self, rule: AvailabilityRule) -> None:
        self._s.add(
            m.AvailabilityRuleModel(
                id=rule.id,
                tenant_id=rule.tenant_id,
                owner_kind=rule.owner_kind,
                owner_id=rule.owner_id,
                weekday=rule.weekday,
                start_time=rule.start_time,
                end_time=rule.end_time,
                effective_from=rule.effective_from,
                effective_until=rule.effective_until,
                is_active=rule.is_active,
                created_at=rule.created_at,
            )
        )

    async def rules_for_owners(
        self, tenant_id: TenantId, owner_ids: list[uuid.UUID]
    ) -> dict[object, list[AvailabilityRule]]:
        """Every rule for every owner in one statement.

        One query rather than one per resource: an availability search over ten
        staff would otherwise be eleven round trips before any work happens.
        """
        if not owner_ids:
            return {}
        rows = (
            await self._s.execute(
                select(m.AvailabilityRuleModel).where(
                    m.AvailabilityRuleModel.tenant_id == tenant_id,
                    m.AvailabilityRuleModel.owner_id.in_(owner_ids),
                    m.AvailabilityRuleModel.is_active.is_(True),
                )
            )
        ).scalars().all()
        grouped: dict[object, list[AvailabilityRule]] = {}
        for row in rows:
            grouped.setdefault(row.owner_id, []).append(rule_to_domain(row))
        return grouped

    async def list_rules(
        self, tenant_id: TenantId, owner_id: uuid.UUID
    ) -> list[AvailabilityRule]:
        rows = (
            await self._s.execute(
                select(m.AvailabilityRuleModel)
                .where(
                    m.AvailabilityRuleModel.tenant_id == tenant_id,
                    m.AvailabilityRuleModel.owner_id == owner_id,
                )
                .order_by(
                    m.AvailabilityRuleModel.weekday, m.AvailabilityRuleModel.start_time
                )
            )
        ).scalars().all()
        return [rule_to_domain(r) for r in rows]

    async def delete_rule(self, tenant_id: TenantId, rule_id: AvailabilityRuleId) -> None:
        await self._s.execute(
            delete(m.AvailabilityRuleModel).where(
                m.AvailabilityRuleModel.tenant_id == tenant_id,
                m.AvailabilityRuleModel.id == rule_id,
            )
        )

    async def add_block(self, block: BlockedPeriod) -> None:
        self._s.add(
            m.BlockedPeriodModel(
                id=block.id,
                tenant_id=block.tenant_id,
                owner_kind=block.owner_kind,
                owner_id=block.owner_id,
                starts_at=block.starts_at,
                ends_at=block.ends_at,
                reason=block.reason,
                created_at=block.created_at,
            )
        )

    async def blocks_for_owners(
        self,
        tenant_id: TenantId,
        owner_ids: list[uuid.UUID],
        window_start: datetime,
        window_end: datetime,
    ) -> dict[object, list[BlockedPeriod]]:
        """Blocks overlapping the window, for every owner, in one statement."""
        if not owner_ids:
            return {}
        rows = (
            await self._s.execute(
                select(m.BlockedPeriodModel).where(
                    m.BlockedPeriodModel.tenant_id == tenant_id,
                    m.BlockedPeriodModel.owner_id.in_(owner_ids),
                    # Standard overlap: starts before the window ends AND ends
                    # after it starts.
                    m.BlockedPeriodModel.starts_at < window_end,
                    m.BlockedPeriodModel.ends_at > window_start,
                )
            )
        ).scalars().all()
        grouped: dict[object, list[BlockedPeriod]] = {}
        for row in rows:
            grouped.setdefault(row.owner_id, []).append(block_to_domain(row))
        return grouped

    async def list_blocks(
        self, tenant_id: TenantId, owner_id: uuid.UUID
    ) -> list[BlockedPeriod]:
        rows = (
            await self._s.execute(
                select(m.BlockedPeriodModel)
                .where(
                    m.BlockedPeriodModel.tenant_id == tenant_id,
                    m.BlockedPeriodModel.owner_id == owner_id,
                )
                .order_by(m.BlockedPeriodModel.starts_at)
            )
        ).scalars().all()
        return [block_to_domain(r) for r in rows]

    async def delete_block(self, tenant_id: TenantId, block_id: BlockedPeriodId) -> None:
        await self._s.execute(
            delete(m.BlockedPeriodModel).where(
                m.BlockedPeriodModel.tenant_id == tenant_id,
                m.BlockedPeriodModel.id == block_id,
            )
        )


class AppointmentRepositoryImpl:
    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    async def add(self, appointment: Appointment) -> None:
        self._s.add(
            m.AppointmentModel(
                id=appointment.id,
                tenant_id=appointment.tenant_id,
                location_id=appointment.location_id,
                service_id=appointment.service_id,
                starts_at=appointment.starts_at,
                ends_at=appointment.ends_at,
                customer_name=appointment.customer_name,
                customer_phone=appointment.customer_phone,
                customer_email=appointment.customer_email,
                customer_timezone=appointment.customer_timezone,
                timezone=appointment.timezone,
                status=appointment.status,
                source=appointment.source,
                resource_ids=[str(r) for r in appointment.resource_ids],
                customer_notes=appointment.customer_notes,
                internal_notes=appointment.internal_notes,
                rescheduled_from_id=appointment.rescheduled_from_id,
                cancellation_reason=appointment.cancellation_reason,
                idempotency_key=appointment.idempotency_key,
                created_by=appointment.created_by,
                created_at=appointment.created_at,
                updated_at=appointment.updated_at,
            )
        )

    async def get(
        self, tenant_id: TenantId, appointment_id: AppointmentId
    ) -> Appointment | None:
        row = (
            await self._s.execute(
                select(m.AppointmentModel).where(
                    m.AppointmentModel.tenant_id == tenant_id,
                    m.AppointmentModel.id == appointment_id,
                )
            )
        ).scalar_one_or_none()
        return appointment_to_domain(row) if row else None

    async def get_by_idempotency_key(
        self, tenant_id: TenantId, key: str
    ) -> Appointment | None:
        """The prior result of a retried create, if there was one.

        Checked before booking so a client that retries after a timeout gets the
        appointment it already made instead of a second one.
        """
        if not key:
            return None
        row = (
            await self._s.execute(
                select(m.AppointmentModel).where(
                    m.AppointmentModel.tenant_id == tenant_id,
                    m.AppointmentModel.idempotency_key == key,
                )
            )
        ).scalar_one_or_none()
        return appointment_to_domain(row) if row else None

    async def list_for_tenant(
        self,
        tenant_id: TenantId,
        *,
        window_start: datetime | None = None,
        window_end: datetime | None = None,
        location_id: LocationId | None = None,
        service_id: ServiceId | None = None,
        resource_id: ResourceId | None = None,
        statuses: list[str] | None = None,
        search: str = "",
        limit: int = 200,
        offset: int = 0,
    ) -> list[Appointment]:
        stmt = select(m.AppointmentModel).where(m.AppointmentModel.tenant_id == tenant_id)
        if window_start is not None:
            stmt = stmt.where(m.AppointmentModel.ends_at > window_start)
        if window_end is not None:
            stmt = stmt.where(m.AppointmentModel.starts_at < window_end)
        if location_id is not None:
            stmt = stmt.where(m.AppointmentModel.location_id == location_id)
        if service_id is not None:
            stmt = stmt.where(m.AppointmentModel.service_id == service_id)
        if resource_id is not None:
            # Containment against the denormalized JSONB list, which is why that
            # column exists: the calendar filters by staff on every render.
            stmt = stmt.where(
                m.AppointmentModel.resource_ids.contains([str(resource_id)])
            )
        if statuses:
            stmt = stmt.where(m.AppointmentModel.status.in_(statuses))
        if search:
            like = f"%{search.lower()}%"
            stmt = stmt.where(
                or_(
                    m.AppointmentModel.customer_name.ilike(like),
                    m.AppointmentModel.customer_phone.ilike(like),
                    m.AppointmentModel.customer_email.ilike(like),
                )
            )
        rows = (
            await self._s.execute(
                stmt.order_by(m.AppointmentModel.starts_at).limit(limit).offset(offset)
            )
        ).scalars().all()
        return [appointment_to_domain(r) for r in rows]

    async def update(self, appointment: Appointment) -> None:
        await self._s.execute(
            update(m.AppointmentModel)
            .where(
                m.AppointmentModel.tenant_id == appointment.tenant_id,
                m.AppointmentModel.id == appointment.id,
            )
            .values(
                starts_at=appointment.starts_at,
                ends_at=appointment.ends_at,
                customer_name=appointment.customer_name,
                customer_phone=appointment.customer_phone,
                customer_email=appointment.customer_email,
                customer_timezone=appointment.customer_timezone,
                timezone=appointment.timezone,
                status=appointment.status,
                resource_ids=[str(r) for r in appointment.resource_ids],
                customer_notes=appointment.customer_notes,
                internal_notes=appointment.internal_notes,
                rescheduled_from_id=appointment.rescheduled_from_id,
                cancellation_reason=appointment.cancellation_reason,
                updated_at=appointment.updated_at,
            )
        )

    async def add_status_change(self, change: StatusChange) -> None:
        self._s.add(
            m.AppointmentStatusHistoryModel(
                id=change.id,
                tenant_id=change.tenant_id,
                appointment_id=change.appointment_id,
                from_status=change.from_status,
                to_status=change.to_status,
                actor_kind=change.actor_kind,
                actor_id=change.actor_id,
                actor_label=change.actor_label,
                channel=change.channel,
                reason=change.reason,
                occurred_at=change.occurred_at,
            )
        )

    async def history(
        self, tenant_id: TenantId, appointment_id: AppointmentId
    ) -> list[StatusChange]:
        rows = (
            await self._s.execute(
                select(m.AppointmentStatusHistoryModel)
                .where(
                    m.AppointmentStatusHistoryModel.tenant_id == tenant_id,
                    m.AppointmentStatusHistoryModel.appointment_id == appointment_id,
                )
                .order_by(m.AppointmentStatusHistoryModel.occurred_at)
            )
        ).scalars().all()
        return [status_change_to_domain(r) for r in rows]

    async def counts_by_status(
        self, tenant_id: TenantId, window_start: datetime, window_end: datetime
    ) -> dict[str, int]:
        """Status tallies for the dashboard, computed in the database."""
        rows = (
            await self._s.execute(
                select(m.AppointmentModel.status, func.count())
                .where(
                    m.AppointmentModel.tenant_id == tenant_id,
                    m.AppointmentModel.starts_at >= window_start,
                    m.AppointmentModel.starts_at < window_end,
                )
                .group_by(m.AppointmentModel.status)
            )
        ).all()
        return dict(rows)  # type: ignore[arg-type]


class ReservationRepositoryImpl:
    """Claimed time — and the seam where the database's guarantee becomes a
    domain error.

    Every write here can lose a race, and losing is normal rather than
    exceptional: two people wanted the same slot and one of them got it. The
    exclusion constraint from migration 0025 decides, and this class translates
    its violation into `ConflictError` so callers never see a driver exception.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    async def busy_intervals(
        self,
        tenant_id: TenantId,
        resource_ids: list[ResourceId],
        window_start: datetime,
        window_end: datetime,
        now: datetime,
    ) -> dict[ResourceId, list[Interval]]:
        """Live reservations overlapping the window, keyed by resource.

        Holds are included alongside bookings on purpose: a slot someone is
        midway through booking must not be offered to the next caller.
        """
        if not resource_ids:
            return {}
        rows = (
            await self._s.execute(
                select(m.ResourceReservationModel).where(
                    m.ResourceReservationModel.tenant_id == tenant_id,
                    m.ResourceReservationModel.resource_id.in_(resource_ids),
                    m.ResourceReservationModel.released_at.is_(None),
                    m.ResourceReservationModel.starts_at < window_end,
                    m.ResourceReservationModel.ends_at > window_start,
                    # An expired hold is not busy time. Filtered in SQL as well
                    # as being purged, so a slot is never withheld just because
                    # the housekeeping sweep has not run yet.
                    or_(
                        m.ResourceReservationModel.expires_at.is_(None),
                        m.ResourceReservationModel.expires_at > now,
                    ),
                )
            )
        ).scalars().all()
        grouped: dict[ResourceId, list[Interval]] = {}
        for row in rows:
            grouped.setdefault(ResourceId(row.resource_id), []).append(
                Interval(row.starts_at, row.ends_at)
            )
        return grouped

    async def purge_expired_holds(
        self, tenant_id: TenantId, resource_ids: list[ResourceId], now: datetime
    ) -> int:
        """Release holds that have timed out on the resources we are about to book.

        Called inside the booking transaction, before the insert. That placement
        is deliberate: correctness must not depend on a background sweep having
        run, or an abandoned booking would keep a slot dead until housekeeping
        noticed. The sweep still exists, but only as tidying.
        """
        if not resource_ids:
            return 0
        result = await self._s.execute(
            update(m.ResourceReservationModel)
            .where(
                m.ResourceReservationModel.tenant_id == tenant_id,
                m.ResourceReservationModel.resource_id.in_(resource_ids),
                m.ResourceReservationModel.kind == "hold",
                m.ResourceReservationModel.released_at.is_(None),
                m.ResourceReservationModel.expires_at <= now,
            )
            .values(released_at=now)
        )
        return _rowcount(result)

    async def reserve(
        self,
        tenant_id: TenantId,
        resource_ids: list[ResourceId],
        window: Interval,
        *,
        kind: str,
        appointment_id: AppointmentId | None = None,
        hold_token: str | None = None,
        expires_at: datetime | None = None,
    ) -> None:
        """Claim `window` on every resource, or raise `ConflictError`.

        All-or-nothing: the rows go in inside a savepoint, so a clash on the
        third resource does not leave the first two claimed. Without the
        savepoint the failed INSERT would poison the surrounding transaction and
        the caller could not respond with a clean 409 at all.
        """
        try:
            async with self._s.begin_nested():
                for resource_id in resource_ids:
                    self._s.add(
                        m.ResourceReservationModel(
                            id=uuid.uuid4(),
                            tenant_id=tenant_id,
                            resource_id=resource_id,
                            starts_at=window.start,
                            ends_at=window.end,
                            kind=kind,
                            appointment_id=appointment_id,
                            hold_token=hold_token,
                            expires_at=expires_at,
                        )
                    )
                await self._s.flush()
        except DBAPIError as exc:
            if _is_slot_conflict(exc):
                raise ConflictError(
                    "That time was just taken. Please choose another slot."
                ) from exc
            # Anything else is a bug, not a busy calendar — let it surface as a
            # 500 rather than telling the customer to pick another time.
            raise

    async def hold_by_token(
        self, tenant_id: TenantId, token: str, now: datetime
    ) -> list[HeldReservation]:
        """The live rows behind a hold token — empty if it expired or was used."""
        if not token:
            return []
        rows = (
            await self._s.execute(
                select(m.ResourceReservationModel).where(
                    m.ResourceReservationModel.tenant_id == tenant_id,
                    m.ResourceReservationModel.hold_token == token,
                    m.ResourceReservationModel.kind == "hold",
                    m.ResourceReservationModel.released_at.is_(None),
                    m.ResourceReservationModel.expires_at > now,
                )
            )
        ).scalars().all()
        return [
            HeldReservation(
                resource_id=ResourceId(r.resource_id),
                starts_at=r.starts_at,
                ends_at=r.ends_at,
            )
            for r in rows
        ]

    async def convert_hold(
        self, tenant_id: TenantId, token: str, appointment_id: AppointmentId
    ) -> int:
        """Turn a hold into the booking it was standing in for.

        An UPDATE rather than a release-and-insert: the rows never leave the
        constraint's scope, so there is no instant in which the slot is free for
        somebody else to take.
        """
        result = await self._s.execute(
            update(m.ResourceReservationModel)
            .where(
                m.ResourceReservationModel.tenant_id == tenant_id,
                m.ResourceReservationModel.hold_token == token,
                m.ResourceReservationModel.kind == "hold",
                m.ResourceReservationModel.released_at.is_(None),
            )
            .values(
                kind="booking",
                appointment_id=appointment_id,
                hold_token=None,
                expires_at=None,
            )
        )
        return _rowcount(result)

    async def release_hold(self, tenant_id: TenantId, token: str, now: datetime) -> int:
        result = await self._s.execute(
            update(m.ResourceReservationModel)
            .where(
                m.ResourceReservationModel.tenant_id == tenant_id,
                m.ResourceReservationModel.hold_token == token,
                m.ResourceReservationModel.kind == "hold",
                m.ResourceReservationModel.released_at.is_(None),
            )
            .values(released_at=now)
        )
        return _rowcount(result)

    async def release_for_appointment(
        self, tenant_id: TenantId, appointment_id: AppointmentId, now: datetime
    ) -> int:
        """Give the calendar back when an appointment is cancelled or moved.

        The row is marked released rather than deleted: it stays as a record of
        what was held, while leaving the constraint's scope so the slot can be
        booked again.
        """
        result = await self._s.execute(
            update(m.ResourceReservationModel)
            .where(
                m.ResourceReservationModel.tenant_id == tenant_id,
                m.ResourceReservationModel.appointment_id == appointment_id,
                m.ResourceReservationModel.released_at.is_(None),
            )
            .values(released_at=now)
        )
        return _rowcount(result)

    async def sweep_expired(self, now: datetime, limit: int = 500) -> int:
        """Cross-tenant housekeeping for the background sweep.

        Not tenant-scoped because it runs from the app's own loop with no
        request behind it, and it only ever releases holds that have already
        expired — a row nobody may still book. Bounded so one tick cannot turn
        into an unbounded UPDATE.
        """
        subquery = (
            select(m.ResourceReservationModel.id)
            .where(
                m.ResourceReservationModel.kind == "hold",
                m.ResourceReservationModel.released_at.is_(None),
                m.ResourceReservationModel.expires_at <= now,
            )
            .limit(limit)
            .scalar_subquery()
        )
        result = await self._s.execute(
            update(m.ResourceReservationModel)
            .where(m.ResourceReservationModel.id.in_(subquery))
            .values(released_at=now)
        )
        return _rowcount(result)


__all__ = [
    "IDEMPOTENCY_CONSTRAINT",
    "OVERLAP_CONSTRAINT",
    "AppointmentRepositoryImpl",
    "AvailabilityRepositoryImpl",
    "LocationRepositoryImpl",
    "ReservationRepositoryImpl",
    "ResourceRepositoryImpl",
    "ServiceRepositoryImpl",
    "appointment_to_domain",
    "block_to_domain",
    "location_to_domain",
    "resource_to_domain",
    "rule_to_domain",
    "service_to_domain",
    "status_change_to_domain",
]
