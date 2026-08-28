"""Slack delivery via an incoming webhook.

Incoming webhooks need no OAuth app and no token refresh — the URL *is* the
credential — which is what makes Slack the one messaging integration that works
end to end without a vendor app registration.
"""

from __future__ import annotations

import httpx
import structlog

from src.infrastructure.http_client import get_client

log = structlog.get_logger(__name__)

TIMEOUT_SECONDS = 15
# Slack renders at most ~3000 chars per section block; a long transcript is
# truncated rather than rejected, since the summary above it is the useful part.
MAX_BLOCK_CHARS = 2800


class SlackSender:
    async def send(
        self, webhook_url: str, text: str, blocks: list[dict] | None = None
    ) -> tuple[bool, str]:
        """Post a message. Returns `(delivered, error)`, never raises."""
        payload: dict = {"text": text}
        if blocks:
            payload["blocks"] = blocks
        try:
            client = await get_client("slack", timeout=TIMEOUT_SECONDS)
            resp = await client.post(webhook_url, json=payload)
        except httpx.HTTPError as exc:
            log.warning("slack.send_error", error=str(exc))
            return False, f"Could not reach Slack: {exc}"
        if resp.status_code >= 400:
            # Slack replies with a plain-text reason ("no_service", "invalid_payload").
            return False, f"Slack rejected the message: {resp.text[:200]}"
        return True, ""

    async def send_post_call(self, webhook_url: str, payload: dict) -> tuple[bool, str]:
        """Render and deliver a post-call payload.

        The application layer calls this rather than composing blocks itself —
        Slack's message format is an infrastructure detail.
        """
        text, blocks = post_call_blocks(payload)
        return await self.send(webhook_url, text, blocks)


def post_call_blocks(payload: dict) -> tuple[str, list[dict]]:
    """Render a post-call payload as Slack blocks.

    Returns `(fallback_text, blocks)` — the fallback is what shows in
    notifications and on clients that don't render blocks.
    """
    chatbot = payload.get("chatbot", "Assistant")
    status = payload.get("call_status", "completed")
    fallback = f"Post-call report — {chatbot} ({status})"
    count = payload.get("message_count", 0)

    blocks: list[dict] = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": f"Post-call report — {chatbot}"},
        },
        {
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": f"*Outcome:* {status}  ·  *Messages:* {count}",
                }
            ],
        },
    ]

    contact = payload.get("contact")
    if contact:
        pretty = "  ·  ".join(f"*{k}:* {v}" for k, v in contact.items() if v)
        if pretty:
            blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": pretty}})

    if payload.get("call_summary"):
        blocks.append(_section("Summary", payload["call_summary"]))

    sentiment = payload.get("sentiment_analysis")
    if sentiment:
        blocks.append(
            _section(
                "Sentiment",
                f"{sentiment.get('label', 'unknown')} ({sentiment.get('score', 'n/a')}) — "
                f"{sentiment.get('rationale', '')}",
            )
        )

    extracted = payload.get("extracted_information")
    if extracted:
        lines = "\n".join(
            f"• *{k}:* {v}" for k, v in extracted.items() if v not in (None, "")
        )
        blocks.append(_section("Extracted information", lines or "_Nothing found_"))

    if payload.get("full_conversation"):
        blocks.append(_section("Transcript", f"```{payload['full_conversation']}```"))

    return fallback, blocks


def _section(title: str, body: str) -> dict:
    text = f"*{title}*\n{body}"
    if len(text) > MAX_BLOCK_CHARS:
        text = text[: MAX_BLOCK_CHARS - 20] + "\n…_(truncated)_"
    return {"type": "section", "text": {"type": "mrkdwn", "text": text}}
