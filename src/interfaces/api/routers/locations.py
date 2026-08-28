"""Locations — the branches a business takes appointments at (spec section 34).

Configuration, so Owner/Admin only. Each branch owns its own timezone, which is
the value every weekly availability rule underneath it is resolved against.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException

from src.domain.scheduling.entities import Location
from src.domain.shared.identifiers import LocationId
from src.interfaces.api.deps import AdminPrincipalDep, ContainerDep
from src.interfaces.api.schemas import LocationRequest, LocationResponse

router = APIRouter(prefix="/locations", tags=["scheduling"])


def to_response(location: Location) -> LocationResponse:
    return LocationResponse(
        id=location.id,
        name=location.name,
        timezone=location.timezone,
        address=location.address,
        phone=location.phone,
        email=location.email,
        is_active=location.is_active,
        created_at=location.created_at,
    )


@router.get("", response_model=list[LocationResponse])
async def list_locations(
    principal: AdminPrincipalDep,
    container: ContainerDep,
    active_only: bool = False,
) -> list[LocationResponse]:
    async with container.unit_of_work() as uow:
        uow.set_tenant_scope(principal.tenant_id)
        locations = await uow.locations.list_for_tenant(
            principal.tenant_id, active_only=active_only
        )
    return [to_response(loc) for loc in locations]


@router.post("", response_model=LocationResponse, status_code=201)
async def create_location(
    body: LocationRequest,
    principal: AdminPrincipalDep,
    container: ContainerDep,
) -> LocationResponse:
    location = Location(
        tenant_id=principal.tenant_id,
        name=body.name,
        timezone=body.timezone,
        address=body.address,
        phone=body.phone,
        email=body.email,
        is_active=body.is_active,
    ).normalized()

    # Validated here rather than at booking time: an unknown zone stored on a
    # branch turns every later availability query for it into an exception, far
    # from the typo that caused it.
    error = location.validation_error()
    if error:
        raise HTTPException(status_code=422, detail=error)

    async with container.unit_of_work() as uow:
        uow.set_tenant_scope(principal.tenant_id)
        await uow.locations.add(location)
        await uow.commit()
    return to_response(location)


@router.get("/{location_id}", response_model=LocationResponse)
async def get_location(
    location_id: uuid.UUID,
    principal: AdminPrincipalDep,
    container: ContainerDep,
) -> LocationResponse:
    async with container.unit_of_work() as uow:
        uow.set_tenant_scope(principal.tenant_id)
        location = await uow.locations.get(principal.tenant_id, LocationId(location_id))
    if location is None:
        raise HTTPException(status_code=404, detail="Location not found")
    return to_response(location)


@router.put("/{location_id}", response_model=LocationResponse)
async def update_location(
    location_id: uuid.UUID,
    body: LocationRequest,
    principal: AdminPrincipalDep,
    container: ContainerDep,
) -> LocationResponse:
    async with container.unit_of_work() as uow:
        uow.set_tenant_scope(principal.tenant_id)
        location = await uow.locations.get(principal.tenant_id, LocationId(location_id))
        if location is None:
            raise HTTPException(status_code=404, detail="Location not found")

        location.name = body.name
        location.timezone = body.timezone
        location.address = body.address
        location.phone = body.phone
        location.email = body.email
        location.is_active = body.is_active
        location.updated_at = datetime.now(UTC)
        location = location.normalized()

        error = location.validation_error()
        if error:
            raise HTTPException(status_code=422, detail=error)

        await uow.locations.update(location)
        await uow.commit()
    return to_response(location)


@router.delete("/{location_id}", status_code=204)
async def deactivate_location(
    location_id: uuid.UUID,
    principal: AdminPrincipalDep,
    container: ContainerDep,
) -> None:
    """Deactivate, never delete.

    Appointments reference their location with ON DELETE RESTRICT, and a branch
    that closes still has history worth keeping. Deactivating removes it from
    every picker while leaving past appointments readable.
    """
    async with container.unit_of_work() as uow:
        uow.set_tenant_scope(principal.tenant_id)
        location = await uow.locations.get(principal.tenant_id, LocationId(location_id))
        if location is None:
            raise HTTPException(status_code=404, detail="Location not found")
        location.is_active = False
        location.updated_at = datetime.now(UTC)
        await uow.locations.update(location)
        await uow.commit()
