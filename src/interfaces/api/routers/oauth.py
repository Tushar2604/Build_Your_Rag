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
    the tokens and replies with a tiny page that posts a message to the opener
    and closes itself.
  * `/{provider}` (DELETE) — disconnect.

**State is a signed JWT**, not a random string in a table: it carries the tenant
id and an expiry, so the callback can attribute the consent without a session
(the popup may not share one) and a replayed or forged `state` is rejected
outright. Ten minutes is plenty for a consent screen and short enough that a
leaked URL is worthless.
"""

from __future__ import annotations

import html
import uuid
from datetime import UTC, datetime, timedelta

import jwt
from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse

from src.application.ports.repositories import OAuthConnection
from src.config.settings import get_settings
from src.domain.shared.identifiers import TenantId
from src.infrastructure.oauth.providers import PROVIDER_SPECS
from src.interfaces.api.deps import AdminPrincipalDep, ContainerDep, PrincipalDep
from src.interfaces.api.schemas import (
    OAuthStartResponse,
    OAuthStatusResponse,
)

router = APIRouter(prefix="/integrations/oauth", tags=["integrations"])

_STATE_TTL_MINUTES = 10
# Namespaces the token so a state JWT can never be presented as an access token
# (and vice versa) — both are signed with the same secret.
_STATE_AUDIENCE = "oauth-state"


def _sign_state(tenant_id: str, provider: str) -> str:
    return jwt.encode(
        {
            "tenant_id": tenant_id,
            "provider": provider,
            "aud": _STATE_AUDIENCE,
            "exp": datetime.now(UTC) + timedelta(minutes=_STATE_TTL_MINUTES),
        },
        get_settings().jwt_secret,
        algorithm="HS256",
    )


def _verify_state(state: str, provider: str) -> TenantId:
    try:
        payload = jwt.decode(
            state,
            get_settings().jwt_secret,
            algorithms=["HS256"],
            audience=_STATE_AUDIENCE,
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail="Invalid or expired OAuth state") from exc

    # The provider is bound into the state so a consent obtained for one
    # integration cannot be redeemed as another (whose scopes may be wider).
    if payload.get("provider") != provider:
        raise HTTPException(status_code=400, detail="OAuth state does not match this provider")
    return TenantId(uuid.UUID(str(payload["tenant_id"])))


def _popup_result_page(provider: str, ok: bool, message: str) -> HTMLResponse:
    """The page the popup lands on: tell the opener, then close.

    `postMessage` targets the app's own origin rather than "*", so a page that
    happens to have opened this popup cannot read the result. The window closes
    itself either way; the manual line is there for the case where the browser
    blocks `close()` on a window it didn't script-open.
    """
    origin = get_settings().public_frontend_base
    safe_message = html.escape(message)
    return HTMLResponse(
        f"""<!doctype html>
<html><head><meta charset="utf-8"><title>{"Connected" if ok else "Connection failed"}</title>
<style>
  body {{ font-family: Inter, system-ui, sans-serif; background:#06090a; color:#eef4f5;
         display:flex; align-items:center; justify-content:center; height:100vh; margin:0; }}
  .box {{ text-align:center; max-width:26rem; padding:2rem; }}
  h1 {{ font-size:1.05rem; margin:0 0 .5rem; }}
  p  {{ font-size:.85rem; color:#8b9a9d; margin:0; line-height:1.6; }}
</style></head>
<body><div class="box">
  <h1>{"✅ Connected" if ok else "⚠️ Connection failed"}</h1>
  <p>{safe_message}</p>
  <p style="margin-top:1rem">You can close this window.</p>
</div>
<script>
  try {{
    window.opener && window.opener.postMessage(
      {{ source: "oauth", provider: {provider!r}, ok: {"true" if ok else "false"} }},
      {origin!r}
    );
  }} catch (e) {{}}
  setTimeout(function () {{ window.close(); }}, {"600" if ok else "2500"});
</script>
</body></html>""",
        status_code=200,
    )


@router.get("/{provider}/start", response_model=OAuthStartResponse)
async def start(
    provider: str, principal: AdminPrincipalDep, container: ContainerDep
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
    state = _sign_state(str(principal.tenant_id), provider)
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
    if client is None:
        return _popup_result_page(provider, False, "Unknown integration.")

    if error or not code:
        return _popup_result_page(
            provider,
            False,
            "Access wasn't granted, so nothing was connected. You can try again "
            "any time.",
        )

    try:
        tenant_id = _verify_state(state, provider)
    except HTTPException as exc:
        return _popup_result_page(provider, False, str(exc.detail))

    try:
        tokens = await client.exchange_code(code)
    except Exception:  # noqa: BLE001 — the vendor's failure, shown as one
        return _popup_result_page(
            provider,
            False,
            f"{client.spec.name} refused the authorization code. Please try "
            f"connecting again.",
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
    return _popup_result_page(
        provider, True, f"{client.spec.name} is connected{who}."
    )


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
