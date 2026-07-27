"""Resend email adapter — candidate interview-invite delivery.

Raw REST call via httpx (Resend's API is a single simple POST, no SDK needed),
same resilience pattern as the LLM providers. If RESEND_API_KEY is unset,
`enabled` is False and callers skip sending entirely rather than erroring —
scheduling an interview never hard-depends on this.
"""

from __future__ import annotations

import httpx
import structlog
from tenacity import retry, stop_after_attempt, wait_exponential

from src.config.settings import Settings

log = structlog.get_logger(__name__)

_API_URL = "https://api.resend.com/emails"


class ResendEmailSender:
    def __init__(self, settings: Settings) -> None:
        self._api_key = settings.resend_api_key
        self._from_email = settings.resend_from_email

    @property
    def enabled(self) -> bool:
        return bool(self._api_key)

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=10))
    async def send(self, *, to: str, subject: str, html: str) -> bool:
        if not self.enabled:
            return False
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                _API_URL,
                headers={"Authorization": f"Bearer {self._api_key}"},
                json={"from": self._from_email, "to": [to], "subject": subject, "html": html},
            )
            if resp.status_code >= 400:
                log.warning("resend.send_failed", status=resp.status_code, body=resp.text[:500])
                return False
            return True
