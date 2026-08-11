"""One-click OAuth connect for every consent-based integration.

The shape of the flow, from the user's side: click Connect, a popup opens on the
vendor's own consent screen, they approve in their own account, the popup closes
itself, and the card says "Connected as them@example.com". No API keys, no
tokens pasted into a form, no leaving the page.

Three endpoints make that work:

  * `/{provider}/start`   — returns the consent URL as JSON. It returns rather
    than redirects because a plain browser navigation would not carry the
    Authorization header (the JWT lives in localStorage, not a cookie), so the
    auth check has to happen over fetch.
  * `/{provider}/callback` — the vendor redirects the *popup* here. It stores
    the tokens and replies with a page that posts a message to the opener and
    closes itself.
  * `/{provider}` (DELETE) — disconnect.

State signing, origin verification and the result page are shared with Google
sign-in — see `interfaces/api/oauth_popup.py`.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse

from src.application.ports.repositories import OAuthConnection
from src.domain.shared.identifiers import TenantId
from src.infrastructure.oauth.providers import PROVIDER_SPECS
from src.interfaces.api.deps import AdminPrincipalDep, ContainerDep, PrincipalDep
from src.interfaces.api.oauth_popup import (
    popup_result_page,
    resolve_origin,
    sign_state,
    state_origin,
    verify_state,
)
from src.interfaces.api.schemas import (
    OAuthStartResponse,
    OAuthStatusResponse,
)

router = APIRouter(prefix="/integrations/oauth", tags=["integrations"])


def _result(provider: str, ok: bool, message: str, origin: str) -> HTMLResponse:
    """Connect-flow result page. The opener keys on `provider` to know which
    card to refresh."""
    return popup_result_page(
        ok=ok, message=message, origin=origin, payload={"provider": provider}
    )

@router.get("/{provider}/start", response_model=OAuthStartResponse)
async def start(
    provider: str, request: Request, principal: AdminPrincipalDep, container: ContainerDep
) -> OAuthStartResponse:
    client = container.oauth.get(provider)
    if client is None:
        raise HTTPException(status_code=404, detail="Unknown integration")
    if not client.enabled:
        raise HTTPException(
            status_code=400,
            detail=(
                f"{client.spec.name} isn't configured on this server yet. An "
                f"administrator needs to register an OAuth app for it and set its "
                f"client id and secret in the environment."
            ),
        )
    # The popup reports back to the origin that opened it, verified here and
    # carried inside the signed state — otherwise a deployment whose SPA and API
    # sit on different origins silently loses the result message.
    origin = resolve_origin(request.headers.get("origin"))
    state = sign_state(provider, origin, tenant_id=str(principal.tenant_id))
    return OAuthStartResponse(authorize_url=client.authorize_url(state))


@router.get("/{provider}/callback")
async def callback(
    provider: str,
    container: ContainerDep,
    code: str | None = None,
    state: str = "",
    error: str | None = None,
) -> HTMLResponse:
    """Where the vendor sends the popup back.

    Deliberately returns a page rather than raising on failure: this window is
    the user's only feedback, and an API error body rendered raw in a popup
    tells them nothing about what to do next.
    """
    client = container.oauth.get(provider)
    fallback_origin = resolve_origin(None)
    if client is None:
        return _result(provider, False, "Unknown integration.", fallback_origin)

    if error or not code:
        return _result(
            provider,
            False,
            "Access wasn't granted, so nothing was connected. You can try again "
            "any time.",
            fallback_origin,
        )

    try:
        payload = verify_state(state, provider)
    except HTTPException as exc:
        return _result(provider, False, str(exc.detail), fallback_origin)

    tenant_id = TenantId(uuid.UUID(str(payload["tenant_id"])))
    origin = state_origin(payload)

    try:
        tokens = await client.exchange_code(code)
    except Exception:  # noqa: BLE001 — the vendor's failure, shown as one
        return _result(
            provider,
            False,
            f"{client.spec.name} refused the authorization code. Please try "
            f"connecting again.",
            origin,
        )

    async with container.unit_of_work() as uow:
        uow.set_tenant_scope(tenant_id)
        await uow.oauth_connections.upsert(
            OAuthConnection(
                tenant_id=tenant_id,
                provider=provider,
                access_token=tokens.access_token,
                refresh_token=tokens.refresh_token,
                expires_at=tokens.expires_at,
                scope=tokens.scope,
                account_label=tokens.account_label,
            )
        )
        await uow.commit()

    who = f" as {tokens.account_label}" if tokens.account_label else ""
    return _result(provider, True, f"{client.spec.name} is connected{who}.", origin)


@router.get("/{provider}/status", response_model=OAuthStatusResponse)
async def status(
    provider: str, principal: PrincipalDep, container: ContainerDep
) -> OAuthStatusResponse:
    if provider not in PROVIDER_SPECS:
        raise HTTPException(status_code=404, detail="Unknown integration")
    client = container.oauth.get(provider)
    async with container.unit_of_work() as uow:
        uow.set_tenant_scope(principal.tenant_id)
        connection = await uow.oauth_connections.get(principal.tenant_id, provider)
    return OAuthStatusResponse(
        provider=provider,
        connected=connection is not None,
        account_label=connection.account_label if connection else "",
        configured=bool(client and client.enabled),
    )


@router.delete("/{provider}", status_code=204)
async def disconnect(
    provider: str, principal: AdminPrincipalDep, container: ContainerDep
) -> None:
    if provider not in PROVIDER_SPECS:
        raise HTTPException(status_code=404, detail="Unknown integration")
    async with container.unit_of_work() as uow:
        uow.set_tenant_scope(principal.tenant_id)
        await uow.oauth_connections.delete(principal.tenant_id, provider)
        await uow.commit()
