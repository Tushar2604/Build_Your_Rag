"""Outbound webhook delivery for post-call payloads.

Signs every request so the receiver can verify it really came from us — an
unauthenticated POST of a candidate transcript into a customer's ATS is exactly
the kind of endpoint that gets spoofed. The scheme mirrors Stripe's: an
`X-Signature-Timestamp` plus an HMAC-SHA256 of `timestamp.body` keyed on the
tenant's own JWT secret.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time

import httpx
import structlog

log = structlog.get_logger(__name__)

TIMEOUT_SECONDS = 15
MAX_BODY_LOG = 500


def sign_payload(secret: str, timestamp: str, body: bytes) -> str:
    signed = f"{timestamp}.".encode() + body
    return hmac.new(secret.encode(), signed, hashlib.sha256).hexdigest()


class WebhookSender:
    def __init__(self, signing_secret: str) -> None:
        self._secret = signing_secret

    async def send(self, url: str, payload: dict) -> tuple[bool, str]:
        """POST the payload. Returns (delivered, error_message).

        Never raises: a customer's broken endpoint must not fail the
        conversation that produced the payload, so every failure mode comes back
        as a message the operator can read in the delivery log.
        """
        body = json.dumps(payload, default=str).encode()
        timestamp = str(int(time.time()))
        headers = {
            "Content-Type": "application/json",
            "User-Agent": "rag-platform-postcall/1",
            "X-Signature-Timestamp": timestamp,
            "X-Signature": sign_payload(self._secret, timestamp, body),
        }
        try:
            async with httpx.AsyncClient(timeout=TIMEOUT_SECONDS) as client:
                resp = await client.post(url, content=body, headers=headers)
        except httpx.HTTPError as exc:
            log.warning("postcall.webhook_error", url=url, error=str(exc))
            return False, f"Could not reach the webhook: {exc}"
        if resp.status_code >= 400:
            log.warning("postcall.webhook_rejected", url=url, status=resp.status_code)
            return False, f"Webhook returned HTTP {resp.status_code}: {resp.text[:MAX_BODY_LOG]}"
        return True, ""
