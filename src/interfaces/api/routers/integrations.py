"""Third-party integrations for the Virtual Interview feature: "Connect
Google Calendar" (per-tenant OAuth). Resend (email) is a plain API key, so it
needs no router — it's configured once in `.env` like every other provider.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import jwt
from fastapi import APIRouter, HTTPException
from fastapi.responses import RedirectResponse

from src.application.ports.repositories import GoogleOAuthConnection
from src.config.settings import get_settings
from src.domain.shared.identifiers import TenantId
from src.interfaces.api.deps import ContainerDep, PrincipalDep
from src.interfaces.api.schemas import GoogleConnectResponse, GoogleStatusResponse

router = APIRouter(prefix="/integrations", tags=["integrations"])

_STATE_TTL_MINUTES = 10


def _sign_state(tenant_id: str) -> str:
    payload = {"tenant_id": tenant_id, "exp": datetime.now(UTC) + timedelta(minutes=_STATE_TTL_MINUTES)}
    return jwt.encode(payload, get_settings().jwt_secret, algorithm="HS256")


def _verify_state(state: str) -> str:
    try:
        payload = jwt.decode(state, get_settings().jwt_secret, algorithms=["HS256"])
        return str(payload["tenant_id"])
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail="Invalid or expired OAuth state") from exc


@router.get("/google/connect", response_model=GoogleConnectResponse)
async def google_connect(principal: PrincipalDep, container: ContainerDep) -> GoogleConnectResponse:
    """Returns the Google consent URL as JSON (rather than redirecting) so the
    frontend can navigate there itself — a plain browser navigation to this
    endpoint wouldn't carry the Authorization header (it lives in
    localStorage, not a cookie), so the auth check has to happen over fetch."""
    if not container.calendar.enabled:
        raise HTTPException(
            status_code=400,
            detail="Google Calendar isn't configured on this server. Add "
            "GOOGLE_OAUTH_CLIENT_ID/SECRET to .env first.",
        )
    state = _sign_state(str(principal.tenant_id))
    return GoogleConnectResponse(authorize_url=container.calendar.authorize_url(state))


@router.get("/google/callback")
async def google_callback(code: str, state: str, container: ContainerDep) -> RedirectResponse:
    tenant_id = TenantId(uuid.UUID(_verify_state(state)))
    tokens = await container.calendar.exchange_code(code)
    email = await container.calendar.fetch_email(tokens["access_token"])

    connection = GoogleOAuthConnection(
        tenant_id=tenant_id,
        access_token=tokens["access_token"],
        refresh_token=tokens.get("refresh_token", ""),
        expires_at=datetime.now(UTC) + timedelta(seconds=tokens.get("expires_in", 3600)),
        scope=tokens.get("scope", ""),
        connected_email=email,
    )
    async with container.unit_of_work() as uow:
        uow.set_tenant_scope(tenant_id)
        await uow.google_connections.upsert(connection)
        await uow.commit()

    return RedirectResponse(f"{get_settings().public_frontend_base}/settings?tab=integrations&connected=1")


@router.get("/google/status", response_model=GoogleStatusResponse)
async def google_status(principal: PrincipalDep, container: ContainerDep) -> GoogleStatusResponse:
    async with container.unit_of_work() as uow:
        uow.set_tenant_scope(principal.tenant_id)
        connection = await uow.google_connections.get(principal.tenant_id)
    return GoogleStatusResponse(
        connected=connection is not None, email=connection.connected_email if connection else ""
    )


@router.delete("/google", status_code=204)
async def google_disconnect(principal: PrincipalDep, container: ContainerDep) -> None:
    async with container.unit_of_work() as uow:
        uow.set_tenant_scope(principal.tenant_id)
        await uow.google_connections.delete(principal.tenant_id)
        await uow.commit()
