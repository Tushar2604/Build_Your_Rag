"""Outbound WhatsApp sends via Twilio's REST API.

Deliberately stateless: credentials arrive per-call from the tenant's own
`whatsapp_channels` row, matching how the inbound webhook already verifies
signatures. Nothing here reads .env, so two tenants can use two Twilio accounts
in the same process.

Only `httpx` is used rather than the `twilio` SDK — the SDK is sync-only and
would block the event loop on every send in a broadcast.
"""

from __future__ import annotations

import contextlib

import httpx
import structlog

from src.infrastructure.http_client import get_client

log = structlog.get_logger(__name__)

_API_BASE = "https://api.twilio.com/2010-04-01"
TIMEOUT_SECONDS = 20


def _wa(number: str) -> str:
    """Twilio addresses WhatsApp endpoints with a `whatsapp:` scheme prefix."""
    n = number.strip()
    return n if n.startswith("whatsapp:") else f"whatsapp:{n}"


class TwilioWhatsAppSender:
    async def send(
        self,
        *,
        account_sid: str,
        auth_token: str,
        from_number: str,
        to_number: str,
        body: str,
        status_callback: str = "",
    ) -> tuple[bool, str, str]:
        """Send one WhatsApp message.

        Returns `(ok, message_sid, error)`. Never raises — a broadcast of 500
        contacts must not abort on the one number that Twilio rejects, so every
        failure comes back as text stored on that recipient's row.
        """
        url = f"{_API_BASE}/Accounts/{account_sid}/Messages.json"
        form = {
            "From": _wa(from_number),
            "To": _wa(to_number),
            "Body": body,
        }
        if status_callback:
            # Without this, delivered/read never arrive and the funnel stalls at
            # "sent" — the campaign console would look broken.
            form["StatusCallback"] = status_callback

        try:
            client = await get_client("twilio", timeout=TIMEOUT_SECONDS)
            resp = await client.post(url, data=form, auth=(account_sid, auth_token))
        except httpx.HTTPError as exc:
            log.warning("whatsapp.send_error", to=to_number, error=str(exc))
            return False, "", f"Could not reach Twilio: {exc}"

        if resp.status_code >= 400:
            detail = _twilio_error(resp)
            log.warning(
                "whatsapp.send_rejected", to=to_number, status=resp.status_code, detail=detail
            )
            return False, "", detail

        # A missing SID only costs us delivery callbacks for this one message,
        # so it isn't worth failing a send that Twilio already accepted.
        sid = ""
        with contextlib.suppress(ValueError):
            sid = str(resp.json().get("sid", ""))
        return True, sid, ""


def _twilio_error(resp: httpx.Response) -> str:
    """Twilio's JSON error body is far more actionable than the status line —
    it names the actual problem ("not a valid WhatsApp number", "outside the
    24-hour session window"), which is what the operator needs to see."""
    try:
        data = resp.json()
    except ValueError:
        return f"Twilio returned HTTP {resp.status_code}: {resp.text[:300]}"
    message = data.get("message") or f"HTTP {resp.status_code}"
    code = data.get("code")
    return f"{message} (Twilio code {code})" if code else str(message)
