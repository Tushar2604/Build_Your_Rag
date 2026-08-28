"""Services — what a customer can book, and what it takes to deliver it.

The eligibility sub-resource is the interesting half. A service names the
resources that can serve it AND the role each fills, which is what makes "a
dentist and a chair" expressible: the availability engine fills every distinct
required role before it will offer a slot.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException

from src.domain.scheduling.entities import Service, ServiceResource
from src.domain.shared.identifiers import ResourceId, ServiceId
from src.interfaces.api.deps import AdminPrincipalDep, ContainerDep
from src.interfaces.api.schemas import (
    ServiceRequest,
    ServiceResourceLink,
    ServiceResponse,
    SetServiceResourcesRequest,
)

router = APIRouter(prefix="/services", tags=["scheduling"])


def to_response(
    service: Service, links: list[ServiceResource] | None = None
) -> ServiceResponse:
    return ServiceResponse(
        id=service.id,
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
        resources=[
            ServiceResourceLink(
                resource_id=link.resource_id, role=link.role, required=link.required
            )
            for link in (links or [])
        ],
        created_at=service.created_at,
    )


def _apply(service: Service, body: ServiceRequest) -> Service:
    service.name = body.name
    service.category = body.category
    service.description = body.description
    service.duration_minutes = body.duration_minutes
    service.buffer_before_minutes = body.buffer_before_minutes
    service.buffer_after_minutes = body.buffer_after_minutes
    service.price_cents = body.price_cents
    service.deposit_cents = body.deposit_cents
    service.currency = body.currency
    service.min_notice_minutes = body.min_notice_minutes
    service.max_horizon_days = body.max_horizon_days
    service.cancellation_window_hours = body.cancellation_window_hours
    service.online_bookable = body.online_bookable
    service.is_active = body.is_active
    return service.normalized()


@router.get("", response_model=list[ServiceResponse])
async def list_services(
    principal: AdminPrincipalDep,
    container: ContainerDep,
    active_only: bool = False,
) -> list[ServiceResponse]:
    async with container.unit_of_work() as uow:
        uow.set_tenant_scope(principal.tenant_id)
        services = await uow.services.list_for_tenant(
            principal.tenant_id, active_only=active_only
        )
        # Eligibility per service. N+1 by construction, and deliberately left
        # that way: a tenant has tens of services, not thousands, and the list
        # is not on any hot path.
        links = {
            service.id: await uow.services.eligibility_for(
                principal.tenant_id, service.id
            )
            for service in services
        }
    return [to_response(s, links.get(s.id)) for s in services]


@router.post("", response_model=ServiceResponse, status_code=201)
async def create_service(
    body: ServiceRequest,
    principal: AdminPrincipalDep,
    container: ContainerDep,
) -> ServiceResponse:
    service = _apply(
        Service(
            tenant_id=principal.tenant_id,
            name=body.name,
            duration_minutes=body.duration_minutes,
        ),
        body,
    )
    error = service.validation_error()
    if error:
        raise HTTPException(status_code=422, detail=error)

    async with container.unit_of_work() as uow:
        uow.set_tenant_scope(principal.tenant_id)
        await uow.services.add(service)
        await uow.commit()
    return to_response(service)


@router.get("/{service_id}", response_model=ServiceResponse)
async def get_service(
    service_id: uuid.UUID,
    principal: AdminPrincipalDep,
    container: ContainerDep,
) -> ServiceResponse:
    async with container.unit_of_work() as uow:
        uow.set_tenant_scope(principal.tenant_id)
        service = await uow.services.get(principal.tenant_id, ServiceId(service_id))
        if service is None:
            raise HTTPException(status_code=404, detail="Service not found")
        links = await uow.services.eligibility_for(principal.tenant_id, service.id)
    return to_response(service, links)


@router.put("/{service_id}", response_model=ServiceResponse)
async def update_service(
    service_id: uuid.UUID,
    body: ServiceRequest,
    principal: AdminPrincipalDep,
    container: ContainerDep,
) -> ServiceResponse:
    async with container.unit_of_work() as uow:
        uow.set_tenant_scope(principal.tenant_id)
        service = await uow.services.get(principal.tenant_id, ServiceId(service_id))
        if service is None:
            raise HTTPException(status_code=404, detail="Service not found")

        service = _apply(service, body)
        service.updated_at = datetime.now(UTC)
        error = service.validation_error()
        if error:
            raise HTTPException(status_code=422, detail=error)

        await uow.services.update(service)
        links = await uow.services.eligibility_for(principal.tenant_id, service.id)
        await uow.commit()
    return to_response(service, links)


@router.put("/{service_id}/resources", response_model=ServiceResponse)
async def set_service_resources(
    service_id: uuid.UUID,
    body: SetServiceResourcesRequest,
    principal: AdminPrincipalDep,
    container: ContainerDep,
) -> ServiceResponse:
    """Replace which resources may serve this service, and in which roles."""
    async with container.unit_of_work() as uow:
        uow.set_tenant_scope(principal.tenant_id)
        service = await uow.services.get(principal.tenant_id, ServiceId(service_id))
        if service is None:
            raise HTTPException(status_code=404, detail="Service not found")

        # Every referenced resource must belong to this tenant. Without this a
        # crafted body could link another tenant's staff into this service and
        # leak their availability through the slot search.
        requested = [ResourceId(link.resource_id) for link in body.resources]
        owned = {
            r.id for r in await uow.resources.list_by_ids(principal.tenant_id, requested)
        }
        missing = [str(r) for r in requested if r not in owned]
        if missing:
            raise HTTPException(
                status_code=404, detail=f"Unknown resource(s): {', '.join(missing)}"
            )

        links = [
            ServiceResource(
                tenant_id=principal.tenant_id,
                service_id=service.id,
                resource_id=ResourceId(link.resource_id),
                role=link.role.strip() or "primary",
                required=link.required,
            )
            for link in body.resources
        ]
        await uow.services.set_eligibility(principal.tenant_id, service.id, links)
        await uow.commit()
    return to_response(service, links)


@router.delete("/{service_id}", status_code=204)
async def deactivate_service(
    service_id: uuid.UUID,
    principal: AdminPrincipalDep,
    container: ContainerDep,
) -> None:
    """Deactivate, never delete — appointments reference it with RESTRICT."""
    async with container.unit_of_work() as uow:
        uow.set_tenant_scope(principal.tenant_id)
        service = await uow.services.get(principal.tenant_id, ServiceId(service_id))
        if service is None:
            raise HTTPException(status_code=404, detail="Service not found")
        service.is_active = False
        service.updated_at = datetime.now(UTC)
        await uow.services.update(service)
        await uow.commit()
