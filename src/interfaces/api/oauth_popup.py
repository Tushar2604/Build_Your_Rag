"""Shared plumbing for the OAuth popup dance.

Both consent flows in this app — connecting an integration, and signing in with
Google — run the identical browser choreography: open a popup, let the vendor
redirect it back here, then hand a result to the window that opened it and
close. Only the payload differs, so the state signing, the origin check and the
result page live here once.

Two things this module is responsible for getting right:

**State is a signed JWT, not a random string in a table.** It carries who
started the flow and where the answer may be delivered, so the callback can
attribute a consent without a session (the popup may not share one) and a forged
or replayed `state` is rejected outright. Ten minutes is long enough for a
consent screen and short enough that a leaked URL is worthless.

**The result is posted to a verified origin.** `postMessage` with `"*"` would
let any page that opened this popup read an access token, so the target is
always an origin the deployment actually serves — checked when the flow starts,
carried inside the signed state, and re-checked before it is used.
"""

from __future__ import annotations

import html
import json
from datetime import UTC, datetime, timedelta

import jwt
from fastapi import HTTPException
from fastapi.responses import HTMLResponse

from src.config.settings import get_settings

STATE_TTL_MINUTES = 10
# Namespaces the token so a state JWT can never be presented as an access token
# (and vice versa) — both are signed with the same secret.
STATE_AUDIENCE = "oauth-state"


def resolve_origin(requested: str | None) -> str:
    """Pick the origin the popup may post its result back to.

    Falls back to the configured frontend rather than rejecting an unknown
    origin: the request may legitimately carry no `Origin` header, and the
    fallback is always a origin this deployment serves.
    """
    settings = get_settings()
    candidate = (requested or "").rstrip("/")
    if candidate and settings.is_allowed_popup_origin(candidate):
        return candidate
    return settings.public_frontend_base


def sign_state(provider: str, origin: str, **claims: str) -> str:
    return jwt.encode(
        {
            "provider": provider,
            "origin": origin,
            "aud": STATE_AUDIENCE,
            "exp": datetime.now(UTC) + timedelta(minutes=STATE_TTL_MINUTES),
            **claims,
        },
        get_settings().jwt_secret,
        algorithm="HS256",
    )


def verify_state(state: str, provider: str) -> dict:
    """Decode a state token, or raise a 400. Never trusts it unverified."""
    try:
        payload = jwt.decode(
            state,
            get_settings().jwt_secret,
            algorithms=["HS256"],
            audience=STATE_AUDIENCE,
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail="Invalid or expired OAuth state") from exc

    # The provider is bound into the state so a consent obtained for one flow
    # cannot be redeemed as another (whose scopes may be wider, or which signs
    # somebody in rather than connecting a calendar).
    if payload.get("provider") != provider:
        raise HTTPException(status_code=400, detail="OAuth state does not match this provider")
    return payload


def state_origin(payload: dict) -> str:
    """The delivery origin from a decoded state, re-checked before use.

    Belt and braces: the state is signed, so this should always pass — but the
    cost of being wrong is posting a session token to somebody else's page, and
    the check is one comparison.
    """
    return resolve_origin(str(payload.get("origin", "")))


def popup_result_page(
    *,
    ok: bool,
    message: str,
    origin: str,
    payload: dict | None = None,
    title_ok: str = "Connected",
    title_failed: str = "Connection failed",
) -> HTMLResponse:
    """The page the popup lands on: tell the opener, then close itself.

    The window closes either way; the "you can close this" line is there for the
    case where a browser blocks `close()` on a window it did not script-open.
    """
    body = json.dumps({"source": "oauth", "ok": ok, **(payload or {})})
    heading = f"✅ {title_ok}" if ok else f"⚠️ {title_failed}"
    return HTMLResponse(
        f"""<!doctype html>
<html><head><meta charset="utf-8"><title>{html.escape(title_ok if ok else title_failed)}</title>
<style>
  body {{ font-family: Inter, system-ui, sans-serif; background:#06090a; color:#eef4f5;
         display:flex; align-items:center; justify-content:center; height:100vh; margin:0; }}
  .box {{ text-align:center; max-width:26rem; padding:2rem; }}
  h1 {{ font-size:1.05rem; margin:0 0 .5rem; }}
  p  {{ font-size:.85rem; color:#8b9a9d; margin:0; line-height:1.6; }}
</style></head>
<body><div class="box">
  <h1>{heading}</h1>
  <p>{html.escape(message)}</p>
  <p style="margin-top:1rem">You can close this window.</p>
</div>
<script>
  try {{
    window.opener && window.opener.postMessage({body}, {json.dumps(origin)});
  }} catch (e) {{}}
  setTimeout(function () {{ window.close(); }}, {"600" if ok else "2500"});
</script>
</body></html>""",
        status_code=200,
    )
