"""The Integrations page — browse the catalogue and connect a tenant to one.

Kept separate from `integrations.py`, which owns the Google Calendar OAuth
dance. This router is the generic credential store + catalogue view; OAuth
integrations appear as cards here but hand off to their own flow.

Secrets never travel back to the browser: responses go through
`catalogue.redact`, which masks every field the spec marks secret.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from src.domain.integration.catalogue import (
    CATALOGUE,
    category_counts,
    get_spec,
    redact,
    validate_credentials,
)
from src.domain.integration.entities import TenantIntegration
from src.interfaces.api.deps import AdminPrincipalDep, ContainerDep, PrincipalDep
from src.interfaces.api.schemas import (
    ConnectIntegrationRequest,
    CredentialFieldSchema,
    IntegrationCardResponse,
    IntegrationCatalogueResponse,
    IntegrationTestResponse,
)

router = APIRouter(prefix="/integrations-catalogue", tags=["integrations"])


def _card(spec, connection: TenantIntegration | None) -> IntegrationCardResponse:
    return IntegrationCardResponse(
        id=spec.id,
        name=spec.name,
        description=spec.description,
        category=spec.category,
        category_label=spec.category_label,
        timing=spec.timing,
        auth=spec.auth,
        credential_fields=[
            CredentialFieldSchema(
                key=cf.key,
                label=cf.label,
                placeholder=cf.placeholder,
                secret=cf.secret,
                required=cf.required,
                help_text=cf.help_text,
            )
            for cf in spec.credential_fields
        ],
        wired=spec.wired,
        unavailable_reason=spec.unavailable_reason,
        oauth_start_path=spec.oauth_start_path,
        connected=connection is not None,
        enabled=connection.enabled if connection else True,
        config=redact(spec, connection.config) if connection else {},
        connected_at=connection.created_at if connection else None,
    )


@router.get("", response_model=IntegrationCatalogueResponse)
async def list_catalogue(
    principal: PrincipalDep, container: ContainerDep
) -> IntegrationCatalogueResponse:
    """Every catalogue entry, merged with this tenant's connection state.

    The whole catalogue is returned in one call — it's a fixed ~14 entries, and
    the page filters/searches client-side, so paginating would only add
    round-trips.
    """
    async with container.unit_of_work() as uow:
        uow.set_tenant_scope(principal.tenant_id)
        connections = await uow.tenant_integrations.list_for_tenant(principal.tenant_id)
        # OAuth consents live in their own table, not in tenant_integrations —
        # they are tokens the vendor issued, not credentials a tenant typed.
        oauth = await uow.oauth_connections.list_for_tenant(principal.tenant_id)

    by_id = {c.integration_id: c for c in connections}
    oauth_by_provider = {c.provider: c for c in oauth}
    configured_providers = container.oauth.enabled_ids()

    cards: list[IntegrationCardResponse] = []
    for spec in CATALOGUE:
        card = _card(spec, by_id.get(spec.id))
        if spec.auth == "oauth":
            # "Wired" for an OAuth card means the server actually has an app
            # registered for that vendor. Claiming otherwise would put a Connect
            # button on a card whose consent screen would reject the request.
            card.wired = spec.id in configured_providers
            if not card.wired and not card.unavailable_reason:
                card.unavailable_reason = (
                    f"{spec.name} needs an OAuth app registered on this server "
                    f"before it can be connected."
                )
            connection = oauth_by_provider.get(spec.id)
            if connection is not None:
                card.connected = True
                card.config = {"account": connection.account_label}
                card.connected_at = connection.created_at
        cards.append(card)

    return IntegrationCatalogueResponse(
        integrations=cards,
        counts=category_counts(),
        connected_count=sum(1 for c in cards if c.connected),
    )


@router.post("/{integration_id}/connect", response_model=IntegrationCardResponse)
async def connect(
    integration_id: str,
    body: ConnectIntegrationRequest,
    principal: AdminPrincipalDep,
    container: ContainerDep,
) -> IntegrationCardResponse:
    spec = get_spec(integration_id)
    if spec is None:
        raise HTTPException(status_code=404, detail="Unknown integration")
    if not spec.wired:
        # Storing credentials for something that can't use them would be a lie
        # told in the database.
        raise HTTPException(
            status_code=400,
            detail=spec.unavailable_reason or f"{spec.name} isn't available yet.",
        )
    if spec.auth == "oauth":
        raise HTTPException(
            status_code=400,
            detail=f"{spec.name} connects through its own authorization flow.",
        )
    if not spec.credential_fields:
        raise HTTPException(
            status_code=400,
            detail=f"{spec.name} is configured elsewhere in the app, not from this page.",
        )

    result = validate_credentials(spec, body.config)
    if result.error:
        raise HTTPException(status_code=400, detail=result.error)

    connection = TenantIntegration(
        tenant_id=principal.tenant_id,
        integration_id=spec.id,
        config=result.config,
    )
    async with container.unit_of_work() as uow:
        uow.set_tenant_scope(principal.tenant_id)
        await uow.tenant_integrations.upsert(connection)
        await uow.commit()
    return _card(spec, connection)


@router.post("/{integration_id}/test", response_model=IntegrationTestResponse)
async def test_connection(
    integration_id: str, principal: AdminPrincipalDep, container: ContainerDep
) -> IntegrationTestResponse:
    """Send a real message so the operator finds out now, not at 2am.

    Only integrations that actually transact can be tested; the rest report why.
    """
    spec = get_spec(integration_id)
    if spec is None:
        raise HTTPException(status_code=404, detail="Unknown integration")

    async with container.unit_of_work() as uow:
        uow.set_tenant_scope(principal.tenant_id)
        connection = await uow.tenant_integrations.get(principal.tenant_id, integration_id)
    if connection is None:
        raise HTTPException(status_code=404, detail=f"{spec.name} isn't connected.")

    if integration_id == "slack":
        ok, error = await container.slack.send(
            connection.webhook_url(),
            "✅ Test message — your assistant platform is connected to this channel.",
        )
        return IntegrationTestResponse(
            ok=ok, message="Sent. Check the channel." if ok else error
        )

    if integration_id == "custom_api":
        ok, error = await container.webhook.send(
            connection.webhook_url(),
            {"event": "test", "message": "Connection test from your assistant platform."},
        )
        return IntegrationTestResponse(
            ok=ok, message="Endpoint accepted the payload." if ok else error
        )

    return IntegrationTestResponse(
        ok=False, message=f"{spec.name} has no test action yet."
    )


@router.delete("/{integration_id}", status_code=204)
async def disconnect(
    integration_id: str, principal: AdminPrincipalDep, container: ContainerDep
) -> None:
    spec = get_spec(integration_id)
    if spec is None:
        raise HTTPException(status_code=404, detail="Unknown integration")
    async with container.unit_of_work() as uow:
        uow.set_tenant_scope(principal.tenant_id)
        if spec.auth == "oauth":
            # Its consent lives in oauth_connections; deleting the (absent)
            # tenant_integrations row would report success and disconnect nothing.
            await uow.oauth_connections.delete(principal.tenant_id, integration_id)
        else:
            await uow.tenant_integrations.delete(principal.tenant_id, integration_id)
        await uow.commit()
