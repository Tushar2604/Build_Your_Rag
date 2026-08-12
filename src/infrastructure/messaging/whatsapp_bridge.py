"""HTTP client for the Node WhatsApp bridge.

The bridge owns the WhatsApp sockets; this is the only way the API talks to it.
Every method returns `(ok, error)` rather than raising, because a bridge that is
still booting (it starts alongside the API) must degrade to a readable message
in the UI, not a 500 on the Channels page.
"""

from __future__ import annotations

import httpx
import structlog

from src.config.settings import Settings

log = structlog.get_logger(__name__)

# Longer than the bridge's own database timeout, deliberately. Starting a
# session makes the bridge load auth state, which on a suspended managed
# database waits out a cold start. Giving up first turns a slow pairing into a
# 502 with an empty error message — the bridge was still working on it.
TIMEOUT_SECONDS = 45
_DISABLED = (
    "Personal WhatsApp linking isn't configured on this server. Set BRIDGE_TOKEN "
    "and run the whatsapp-bridge service."
)


class WhatsAppBridgeClient:
    def __init__(self, settings: Settings) -> None:
        self._base = settings.bridge_base_url.rstrip("/")
        self._token = settings.bridge_token

    @property
    def enabled(self) -> bool:
        return bool(self._token)

    async def _post(self, path: str, payload: dict | None = None) -> tuple[bool, str]:
        if not self.enabled:
            return False, _DISABLED
        try:
            async with httpx.AsyncClient(timeout=TIMEOUT_SECONDS) as client:
                resp = await client.post(
                    f"{self._base}{path}",
                    json=payload or {},
                    headers={"X-Bridge-Token": self._token},
                )
        except httpx.HTTPError as exc:
            log.warning("bridge.unreachable", path=path, error=str(exc))
            return False, (
                "The WhatsApp bridge isn't responding. It may still be starting up — "
                "try again in a few seconds."
            )
        if resp.status_code >= 400:
            return False, _detail(resp)
        return True, ""

    async def start_session(self, session_id: str) -> tuple[bool, str]:
        """Begin pairing, or restore an existing link. The QR arrives
        asynchronously as a bridge event, not in this response."""
        return await self._post(f"/sessions/{session_id}/start")

    async def stop_session(self, session_id: str) -> tuple[bool, str]:
        """Close the socket but keep credentials — resumes without a re-scan."""
        return await self._post(f"/sessions/{session_id}/stop")

    async def logout_session(self, session_id: str) -> tuple[bool, str]:
        """Unlink at WhatsApp and wipe the stored keys."""
        return await self._post(f"/sessions/{session_id}/logout")

    async def send_text(self, session_id: str, jid: str, text: str) -> tuple[bool, str]:
        return await self._post(f"/sessions/{session_id}/send", {"jid": jid, "text": text})

    async def health(self) -> tuple[bool, str]:
        if not self.enabled:
            return False, _DISABLED
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                resp = await client.get(f"{self._base}/healthz")
        except httpx.HTTPError as exc:
            return False, f"Bridge unreachable: {exc}"
        return (resp.status_code < 400), "" if resp.status_code < 400 else _detail(resp)


def _detail(resp: httpx.Response) -> str:
    try:
        return str(resp.json().get("detail", f"HTTP {resp.status_code}"))[:500]
    except ValueError:
        return f"HTTP {resp.status_code}: {resp.text[:200]}"
