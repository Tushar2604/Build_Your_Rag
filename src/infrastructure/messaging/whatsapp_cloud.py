"""Meta WhatsApp Cloud API — webhook verification, payload parsing, sending.

Three jobs, kept in one module because they are three views of one wire format:

  * `verify_meta_signature` — is this delivery really from Meta? The webhook
    URL is public by necessity, so the signature is the *only* thing standing
    between an attacker and words appearing in a customer's thread.
  * `parse_webhook` — turn Meta's deeply nested envelope into flat messages and
    statuses. The nesting is not incidental: one POST can carry several
    numbers, each with several messages, and treating it as "the message" is
    how deliveries get silently dropped under load.
  * `CloudWhatsAppSender` — one outbound text.

Stateless and credential-free by design, exactly like the Twilio sender beside
it: the access token arrives per call from the tenant's own channel row, so two
tenants can run two Meta apps in the same process. The one thing that is *not*
per tenant is the app secret, which belongs to the Meta app fronting them all.

Only `httpx` — no Facebook SDK. The official one is sync and would block the
event loop on every send in a broadcast.
"""

from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass, field
from typing import Any

import httpx
import structlog

from src.infrastructure.http_client import get_client

log = structlog.get_logger(__name__)

GRAPH_BASE = "https://graph.facebook.com"
TIMEOUT_SECONDS = 20

# Meta prefixes the hex digest with the algorithm that produced it.
_SIGNATURE_PREFIX = "sha256="


def verify_meta_signature(raw_body: bytes, header: str, app_secret: str) -> bool:
    """Is this webhook delivery genuinely from Meta?

    HMAC-SHA256 of the **raw** request body, keyed by the app secret, compared
    against `X-Hub-Signature-256`. Raw matters: re-serialising the parsed JSON
    changes whitespace and key order, and the digest with it — the classic way
    this check is written so that it never passes, and is then "fixed" by
    deleting it.

    A blank secret returns False rather than skipping the check. An endpoint
    that accepts unsigned posts because it was misconfigured is worse than one
    that is visibly broken: the failure is silent and the damage is real
    messages sent to real customers.
    """
    if not app_secret or not header:
        return False
    provided = header.strip()
    if provided.startswith(_SIGNATURE_PREFIX):
        provided = provided[len(_SIGNATURE_PREFIX) :]
    expected = hmac.new(app_secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
    # Constant-time — never `==` on a signature.
    return hmac.compare_digest(expected, provided)


def verification_challenge(
    mode: str, token: str, challenge: str, expected_token: str
) -> str | None:
    """Meta's subscription handshake: echo the challenge, or refuse.

    Returns the string to reply with, or None when it should be a 403. Pulled
    out of the router so the comparison itself is testable — it is a secret
    comparison, and those belong somewhere a test can reach.
    """
    if not expected_token:
        return None
    if mode != "subscribe":
        return None
    return challenge if hmac.compare_digest(token, expected_token) else None


@dataclass(frozen=True)
class InboundMessage:
    """One customer message, flattened out of the envelope."""

    message_id: str
    from_number: str
    phone_number_id: str
    text: str
    # "text", "audio", "image", … — kept so the router can say something useful
    # about what it cannot read yet rather than staying silent.
    kind: str = "text"
    contact_name: str = ""
    timestamp: str = ""


@dataclass(frozen=True)
class DeliveryStatus:
    """A sent/delivered/read/failed callback for a message we sent.

    Cloud API reports these on the same webhook as inbound messages, where
    Twilio uses a separate StatusCallback URL — which is why the broadcast
    funnel needs them lifted out here rather than at a second endpoint.
    """

    message_id: str
    status: str
    recipient: str
    error: str = ""


@dataclass
class WebhookPayload:
    messages: list[InboundMessage] = field(default_factory=list)
    statuses: list[DeliveryStatus] = field(default_factory=list)


def parse_webhook(payload: dict[str, Any]) -> WebhookPayload:
    """Flatten `entry[].changes[].value.{messages,statuses}`.

    Tolerant on purpose. Meta adds fields and event types without notice, and a
    parser that raises on an unfamiliar shape turns a new notification type into
    a 500 — which Meta retries, and then throttles the whole subscription for.
    Anything unrecognised is skipped, never fatal.
    """
    result = WebhookPayload()
    for entry in _as_list(payload.get("entry")):
        for change in _as_list(_get(entry, "changes")):
            value = _get(change, "value")
            if not isinstance(value, dict):
                continue
            metadata = value.get("metadata")
            phone_number_id = (
                str(metadata.get("phone_number_id", "")) if isinstance(metadata, dict) else ""
            )
            names = _contact_names(value)

            for raw in _as_list(value.get("messages")):
                if not isinstance(raw, dict):
                    continue
                sender = str(raw.get("from", ""))
                result.messages.append(
                    InboundMessage(
                        message_id=str(raw.get("id", "")),
                        from_number=sender,
                        phone_number_id=phone_number_id,
                        text=_text_of(raw),
                        kind=str(raw.get("type", "")) or "text",
                        contact_name=names.get(sender, ""),
                        timestamp=str(raw.get("timestamp", "")),
                    )
                )

            for raw in _as_list(value.get("statuses")):
                if not isinstance(raw, dict):
                    continue
                errors = _as_list(raw.get("errors"))
                detail = ""
                if errors and isinstance(errors[0], dict):
                    first = errors[0]
                    detail = str(
                        first.get("title") or first.get("message") or first.get("code") or ""
                    )
                result.statuses.append(
                    DeliveryStatus(
                        message_id=str(raw.get("id", "")),
                        status=str(raw.get("status", "")),
                        recipient=str(raw.get("recipient_id", "")),
                        error=detail,
                    )
                )
    return result


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _get(container: Any, key: str) -> Any:
    return container.get(key) if isinstance(container, dict) else None


def _contact_names(value: dict[str, Any]) -> dict[str, str]:
    """WhatsApp profile names, keyed by number.

    Worth lifting: it is the only place a real name appears for a first-time
    contact, and the inbox showing "+971 58 …" for every thread is what makes an
    operator ask where the names went.
    """
    names: dict[str, str] = {}
    for contact in _as_list(value.get("contacts")):
        if not isinstance(contact, dict):
            continue
        profile = contact.get("profile")
        name = str(profile.get("name", "")) if isinstance(profile, dict) else ""
        wa_id = str(contact.get("wa_id", ""))
        if wa_id and name:
            names[wa_id] = name
    return names


def _text_of(message: dict[str, Any]) -> str:
    """The words in a message, whatever wrapper carried them.

    A tapped reply button is a real answer — "1", "Root canal" — and the option
    lists the booking assistant sends are exactly what produces them, so reading
    only `text.body` would make the assistant look deaf to its own buttons.
    """
    kind = str(message.get("type", ""))
    if kind == "text":
        body = message.get("text")
        return str(body.get("body", "")).strip() if isinstance(body, dict) else ""
    if kind == "button":
        body = message.get("button")
        return str(body.get("text", "")).strip() if isinstance(body, dict) else ""
    if kind == "interactive":
        interactive = message.get("interactive")
        if not isinstance(interactive, dict):
            return ""
        for key in ("button_reply", "list_reply"):
            reply = interactive.get(key)
            if isinstance(reply, dict):
                return str(reply.get("title", "")).strip()
        return ""
    # Media, location, contacts, reactions: no text to answer. The caller
    # decides what to say about that; inventing a transcription here would be
    # worse than an honest blank.
    return ""


class CloudWhatsAppSender:
    """One outbound message through Meta's Cloud API."""

    async def send(
        self,
        *,
        phone_number_id: str,
        access_token: str,
        to_number: str,
        body: str,
        api_version: str = "v21.0",
    ) -> tuple[bool, str, str]:
        """Send one WhatsApp text.

        Returns `(ok, message_id, error)` — the same contract as the Twilio
        sender, so the broadcast path can hold either without a branch. Never
        raises: a broadcast of 500 contacts must not abort on the one number
        Meta rejects, so every failure comes back as text for that row.
        """
        url = f"{GRAPH_BASE}/{api_version}/{phone_number_id}/messages"
        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            # Meta wants digits, no "+".
            "to": to_number.lstrip("+").strip(),
            "type": "text",
            # Link previews off: the assistant sends booking confirmations, and
            # a preview card under one turns a two-line reply into a billboard.
            "text": {"preview_url": False, "body": body},
        }
        try:
            client = await get_client("whatsapp_cloud", timeout=TIMEOUT_SECONDS)
            resp = await client.post(
                url,
                json=payload,
                headers={"Authorization": f"Bearer {access_token}"},
            )
        except httpx.HTTPError as exc:
            log.warning("whatsapp_cloud.send_error", to=to_number, error=str(exc))
            return False, "", f"Could not reach the WhatsApp Cloud API: {exc}"

        if resp.status_code >= 400:
            detail = _cloud_error(resp)
            log.warning(
                "whatsapp_cloud.send_rejected",
                to=to_number,
                status=resp.status_code,
                detail=detail,
            )
            return False, "", detail

        message_id = ""
        try:
            messages = resp.json().get("messages") or []
            if messages:
                message_id = str(messages[0].get("id", ""))
        except (ValueError, AttributeError, IndexError):
            # Meta accepted it; losing the id only costs us this one message's
            # delivery callbacks, which is not worth failing a real send over.
            pass
        return True, message_id, ""


def _cloud_error(resp: httpx.Response) -> str:
    """Meta's error body names the actual problem where the status line does not.

    Two are worth recognising on sight, because they are the ones an operator
    will actually hit: code 131047 ("re-engagement message") means the 24-hour
    customer service window has closed and only a template may be sent, and 190
    means the access token has expired or been revoked.
    """
    try:
        error = resp.json().get("error") or {}
    except ValueError:
        return f"WhatsApp Cloud API returned HTTP {resp.status_code}: {resp.text[:300]}"
    if not isinstance(error, dict):
        return f"WhatsApp Cloud API returned HTTP {resp.status_code}"

    code = error.get("code")
    message = str(error.get("message") or f"HTTP {resp.status_code}")
    detail = error.get("error_data")
    if isinstance(detail, dict) and detail.get("details"):
        message = f"{message} — {detail['details']}"
    if code == 131047:
        return (
            "Outside the 24-hour customer service window, so only an approved "
            "template can be sent to this contact."
        )
    if code == 190:
        return "The WhatsApp access token has expired or been revoked. Reconnect the number."
    return f"{message} (Meta code {code})" if code is not None else message
