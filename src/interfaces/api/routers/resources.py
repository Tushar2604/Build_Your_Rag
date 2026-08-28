"""Resources — everything a booking consumes (spec section 10).

Staff, treatment rooms, vehicles, machines: one endpoint, discriminated by
`kind`. Modelling people separately is exactly what stops a scheduler ever being
able to book a meeting room, so the availability engine treats them identically
and this router does too.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException

from src.domain.scheduling.entities import Resource
from src.domain.shared.identifiers import LocationId, ResourceId, UserId
from src.interfaces.api.deps import AdminPrincipalDep, ContainerDep
from src.interfaces.api.schemas import ResourceRequest, ResourceResponse

router = APIRouter(prefix="/resources", tags=["scheduling"])


def to_response(resource: Resource) -> ResourceResponse:
    return ResourceResponse(
        id=resource.id,
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
    )


def _apply(resource: Resource, body: ResourceRequest) -> Resource:
    resource.name = body.name
    resource.kind = body.kind
    resource.location_id = LocationId(body.location_id) if body.location_id else None
    resource.user_id = UserId(body.user_id) if body.user_id else None
    resource.email = body.email
    resource.phone = body.phone
    resource.capacity = body.capacity
    resource.timezone = body.timezone
    resource.color = body.color
    resource.is_active = body.is_active
    return resource.normalized()


@router.get("", response_model=list[ResourceResponse])
async def list_resources(
    principal: AdminPrincipalDep,
    container: ContainerDep,
    location_id: uuid.UUID | None = None,
    kind: str = "",
    active_only: bool = False,
) -> list[ResourceResponse]:
    async with container.unit_of_work() as uow:
        uow.set_tenant_scope(principal.tenant_id)
        resources = await uow.resources.list_for_tenant(
            principal.tenant_id,
            location_id=LocationId(location_id) if location_id else None,
            kind=kind,
            active_only=active_only,
        )
    return [to_response(r) for r in resources]


@router.post("", response_model=ResourceResponse, status_code=201)
async def create_resource(
    body: ResourceRequest,
    principal: AdminPrincipalDep,
    container: ContainerDep,
) -> ResourceResponse:
    resource = _apply(
        Resource(tenant_id=principal.tenant_id, name=body.name), body
    )
    error = resource.validation_error()
    if error:
        raise HTTPException(status_code=422, detail=error)

    async with container.unit_of_work() as uow:
        uow.set_tenant_scope(principal.tenant_id)
        # A resource can only be pinned to a branch this tenant owns. Checked
        # rather than trusted: the id arrives from the client.
        if resource.location_id is not None:
            location = await uow.locations.get(principal.tenant_id, resource.location_id)
            if location is None:
                raise HTTPException(status_code=404, detail="Location not found")
        await uow.resources.add(resource)
        await uow.commit()
    return to_response(resource)


@router.get("/{resource_id}", response_model=ResourceResponse)
async def get_resource(
    resource_id: uuid.UUID,
    principal: AdminPrincipalDep,
    container: ContainerDep,
) -> ResourceResponse:
    async with container.unit_of_work() as uow:
        uow.set_tenant_scope(principal.tenant_id)
        resource = await uow.resources.get(principal.tenant_id, ResourceId(resource_id))
    if resource is None:
        raise HTTPException(status_code=404, detail="Resource not found")
    return to_response(resource)


@router.put("/{resource_id}", response_model=ResourceResponse)
async def update_resource(
    resource_id: uuid.UUID,
    body: ResourceRequest,
    principal: AdminPrincipalDep,
    container: ContainerDep,
) -> ResourceResponse:
    async with container.unit_of_work() as uow:
        uow.set_tenant_scope(principal.tenant_id)
        resource = await uow.resources.get(principal.tenant_id, ResourceId(resource_id))
        if resource is None:
            raise HTTPException(status_code=404, detail="Resource not found")

        resource = _apply(resource, body)
        resource.updated_at = datetime.now(UTC)
        error = resource.validation_error()
        if error:
            raise HTTPException(status_code=422, detail=error)

        if resource.location_id is not None:
            location = await uow.locations.get(principal.tenant_id, resource.location_id)
            if location is None:
                raise HTTPException(status_code=404, detail="Location not found")

        await uow.resources.update(resource)
        await uow.commit()
    return to_response(resource)


@router.delete("/{resource_id}", status_code=204)
async def deactivate_resource(
    resource_id: uuid.UUID,
    principal: AdminPrincipalDep,
    container: ContainerDep,
) -> None:
    """Deactivate, never delete.

    An inactive resource stops being offered for new bookings immediately, while
    the appointments it is already serving keep their assignment — which is what
    someone who has taken a week off actually wants.
    """
    async with container.unit_of_work() as uow:
        uow.set_tenant_scope(principal.tenant_id)
        resource = await uow.resources.get(principal.tenant_id, ResourceId(resource_id))
        if resource is None:
            raise HTTPException(status_code=404, detail="Resource not found")
        resource.is_active = False
        resource.updated_at = datetime.now(UTC)
        await uow.resources.update(resource)
        await uow.commit()
