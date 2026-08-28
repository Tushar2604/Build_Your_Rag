"""Availability: the slot search, plus the rules and blocks that shape it.

`GET /availability` is the authoritative answer to "when can this be booked".
Every channel uses it — the dashboard calendar, the WhatsApp agent, the voice
agent, the public API — and nothing else in the system is allowed to decide that
a time is free. That is what makes spec section 61 enforceable rather than
aspirational: an AI cannot invent a slot because there is no other source of one.

The rule and block endpoints are configuration, so Owner/Admin only. The search
itself is available to any authenticated user, since receptionists need it.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta

from fastapi import APIRouter, HTTPException, Query

from src.application.use_cases.availability import FindAvailability
from src.domain.scheduling.availability import MAX_QUERY_DAYS
from src.domain.scheduling.entities import AvailabilityRule, BlockedPeriod
from src.domain.shared.identifiers import (
    AvailabilityRuleId,
    BlockedPeriodId,
    LocationId,
    ResourceId,
    ServiceId,
)
from src.interfaces.api.deps import AdminPrincipalDep, ContainerDep, PrincipalDep
from src.interfaces.api.schemas import (
    AvailabilityResponse,
    AvailabilityRuleRequest,
    AvailabilityRuleResponse,
    BlockedPeriodRequest,
    BlockedPeriodResponse,
    SlotResponse,
)

router = APIRouter(tags=["scheduling"])

# Slot start granularity the caller may ask for. Bounded at both ends: below a
# minute the grid is meaningless, and above four hours it stops being a grid.
_MIN_GRANULARITY = 5
_MAX_GRANULARITY = 240


@router.get("/availability", response_model=AvailabilityResponse)
async def find_availability(
    principal: PrincipalDep,
    container: ContainerDep,
    location_id: uuid.UUID,
    service_id: uuid.UUID,
    range_start: datetime,
    range_end: datetime,
    resource_id: uuid.UUID | None = None,
    granularity_minutes: int = Query(15, ge=_MIN_GRANULARITY, le=_MAX_GRANULARITY),
    limit: int = Query(200, ge=1, le=500),
) -> AvailabilityResponse:
    """Genuinely bookable slots. Every one has passed notice, horizon, working
    hours, blocks, buffers, and every required resource being simultaneously
    free — so a caller may present these without re-checking anything."""
    if range_end <= range_start:
        raise HTTPException(status_code=422, detail="range_end must be after range_start")
    if range_end - range_start > timedelta(days=MAX_QUERY_DAYS):
        # Bounded so one request cannot ask the engine to materialise a year.
        raise HTTPException(
            status_code=422,
            detail=f"The requested range must be {MAX_QUERY_DAYS} days or less.",
        )

    slots, location, service = await FindAvailability(
        container.unit_of_work()
    ).execute(
        principal.tenant_id,
        location_id=LocationId(location_id),
        service_id=ServiceId(service_id),
        range_start=range_start,
        range_end=range_end,
        resource_id=ResourceId(resource_id) if resource_id else None,
        granularity_minutes=granularity_minutes,
        limit=limit,
    )
    return AvailabilityResponse(
        location_id=location.id,
        service_id=service.id,
        timezone=location.timezone,
        duration_minutes=service.duration_minutes,
        slots=[
            SlotResponse(
                starts_at=s.starts_at,
                ends_at=s.ends_at,
                resource_ids=list(s.resource_ids),
            )
            for s in slots
        ],
    )


# --- Weekly rules -----------------------------------------------------------


@router.get("/availability-rules", response_model=list[AvailabilityRuleResponse])
async def list_rules(
    principal: AdminPrincipalDep,
    container: ContainerDep,
    owner_id: uuid.UUID,
) -> list[AvailabilityRuleResponse]:
    async with container.unit_of_work() as uow:
        uow.set_tenant_scope(principal.tenant_id)
        rules = await uow.availability.list_rules(principal.tenant_id, owner_id)
    return [
        AvailabilityRuleResponse(
            id=r.id,
            owner_kind=r.owner_kind,
            owner_id=r.owner_id,
            weekday=r.weekday,
            start_time=r.start_time,
            end_time=r.end_time,
            effective_from=r.effective_from,
            effective_until=r.effective_until,
            is_active=r.is_active,
        )
        for r in rules
    ]


@router.post("/availability-rules", response_model=AvailabilityRuleResponse, status_code=201)
async def create_rule(
    body: AvailabilityRuleRequest,
    principal: AdminPrincipalDep,
    container: ContainerDep,
) -> AvailabilityRuleResponse:
    rule = AvailabilityRule(
        tenant_id=principal.tenant_id,
        owner_kind=body.owner_kind,
        owner_id=body.owner_id,
        weekday=body.weekday,
        start_time=body.start_time,
        end_time=body.end_time,
        effective_from=body.effective_from,
        effective_until=body.effective_until,
    )
    error = rule.validation_error()
    if error:
        raise HTTPException(status_code=422, detail=error)

    async with container.unit_of_work() as uow:
        uow.set_tenant_scope(principal.tenant_id)
        await _require_owner(uow, principal.tenant_id, body.owner_kind, body.owner_id)
        await uow.availability.add_rule(rule)
        await uow.commit()

    return AvailabilityRuleResponse(
        id=rule.id,
        owner_kind=rule.owner_kind,
        owner_id=rule.owner_id,
        weekday=rule.weekday,
        start_time=rule.start_time,
        end_time=rule.end_time,
        effective_from=rule.effective_from,
        effective_until=rule.effective_until,
        is_active=rule.is_active,
    )


@router.delete("/availability-rules/{rule_id}", status_code=204)
async def delete_rule(
    rule_id: uuid.UUID,
    principal: AdminPrincipalDep,
    container: ContainerDep,
) -> None:
    async with container.unit_of_work() as uow:
        uow.set_tenant_scope(principal.tenant_id)
        await uow.availability.delete_rule(
            principal.tenant_id, AvailabilityRuleId(rule_id)
        )
        await uow.commit()


# --- Absolute closures ------------------------------------------------------


@router.get("/blocked-periods", response_model=list[BlockedPeriodResponse])
async def list_blocks(
    principal: AdminPrincipalDep,
    container: ContainerDep,
    owner_id: uuid.UUID,
) -> list[BlockedPeriodResponse]:
    async with container.unit_of_work() as uow:
        uow.set_tenant_scope(principal.tenant_id)
        blocks = await uow.availability.list_blocks(principal.tenant_id, owner_id)
    return [
        BlockedPeriodResponse(
            id=b.id,
            owner_kind=b.owner_kind,
            owner_id=b.owner_id,
            starts_at=b.starts_at,
            ends_at=b.ends_at,
            reason=b.reason,
        )
        for b in blocks
    ]


@router.post("/blocked-periods", response_model=BlockedPeriodResponse, status_code=201)
async def create_block(
    body: BlockedPeriodRequest,
    principal: AdminPrincipalDep,
    container: ContainerDep,
) -> BlockedPeriodResponse:
    """Book out leave, a holiday, or maintenance.

    Existing appointments inside the window are deliberately left alone: a block
    stops NEW bookings, and silently cancelling someone's confirmed appointment
    because a manager marked a day off would be worse than surfacing the clash
    on the calendar for a human to resolve.
    """
    block = BlockedPeriod(
        tenant_id=principal.tenant_id,
        owner_kind=body.owner_kind,
        owner_id=body.owner_id,
        starts_at=body.starts_at,
        ends_at=body.ends_at,
        reason=body.reason,
    )
    error = block.validation_error()
    if error:
        raise HTTPException(status_code=422, detail=error)

    async with container.unit_of_work() as uow:
        uow.set_tenant_scope(principal.tenant_id)
        await _require_owner(uow, principal.tenant_id, body.owner_kind, body.owner_id)
        await uow.availability.add_block(block)
        await uow.commit()

    return BlockedPeriodResponse(
        id=block.id,
        owner_kind=block.owner_kind,
        owner_id=block.owner_id,
        starts_at=block.starts_at,
        ends_at=block.ends_at,
        reason=block.reason,
    )


@router.delete("/blocked-periods/{block_id}", status_code=204)
async def delete_block(
    block_id: uuid.UUID,
    principal: AdminPrincipalDep,
    container: ContainerDep,
) -> None:
    async with container.unit_of_work() as uow:
        uow.set_tenant_scope(principal.tenant_id)
        await uow.availability.delete_block(
            principal.tenant_id, BlockedPeriodId(block_id)
        )
        await uow.commit()


async def _require_owner(uow, tenant_id, owner_kind: str, owner_id: uuid.UUID) -> None:  # type: ignore[no-untyped-def]
    """The rule's owner must belong to this tenant.

    `owner_id` is polymorphic and therefore carries no foreign key, so nothing
    in the schema stops a crafted body from attaching hours to another tenant's
    branch. This is that check.
    """
    if owner_kind == "location":
        owner = await uow.locations.get(tenant_id, LocationId(owner_id))
    else:
        owner = await uow.resources.get(tenant_id, ResourceId(owner_id))
    if owner is None:
        raise HTTPException(status_code=404, detail=f"{owner_kind.title()} not found")
