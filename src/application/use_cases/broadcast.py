"""Broadcast send sweep and contact-list ingestion.

The sweep claims small batches of pending recipients (`FOR UPDATE SKIP LOCKED`),
sends each one, and records the outcome. It is written to be safely re-entrant:
a free host that sleeps mid-campaign resumes on the next start/retry without
re-messaging anyone, and two workers can run it concurrently.

Each successful send also creates the chat session the recipient's replies will
thread into, so the existing WhatsApp auto-reply path picks the conversation up
with no special-casing for broadcast contacts.
"""

from __future__ import annotations

import asyncio
import csv
import io
import uuid
from dataclasses import dataclass, field

import structlog

from src.application.ports.repositories import UnitOfWork
from src.domain.broadcast.entities import (
    MAX_RECIPIENTS,
    Broadcast,
    BroadcastRecipient,
    normalize_phone,
)
from src.domain.chat.entities import ChatSession, Message, MessageRole
from src.domain.shared.identifiers import TenantId

log = structlog.get_logger(__name__)

# Sent per claim-batch. Small enough that a killed process loses little work,
# large enough that the per-batch transaction overhead stays amortised.
BATCH_SIZE = 20
# Twilio throttles WhatsApp sends; a short gap between messages keeps a large
# campaign from tripping rate limits and failing recipients for no good reason.
INTER_SEND_DELAY_SECONDS = 0.35


@dataclass
class ParsedContacts:
    recipients: list[tuple[str, str]] = field(default_factory=list)  # (phone, name)
    invalid: list[str] = field(default_factory=list)


def parse_contacts(text: str) -> ParsedContacts:
    """Parse a pasted contact blob into (phone, name) pairs.

    Accepts what people actually paste: one number per line, `number, name`, or
    a CSV export with a header. Anything that doesn't normalize to E.164 is
    returned in `invalid` rather than dropped — silently discarding a contact is
    how a campaign quietly under-sends.
    """
    result = ParsedContacts()
    seen: set[str] = set()
    if not text.strip():
        return result

    rows = list(csv.reader(io.StringIO(text.strip())))
    for index, row in enumerate(rows):
        if not row:
            continue
        cells = [c.strip() for c in row if c.strip()]
        if not cells:
            continue

        if not any(normalize_phone(c) for c in cells):
            # A CSV header is by definition the first row — restricting the
            # check to index 0 stops a later line like "not a number" being
            # mistaken for one and silently dropped.
            joined = " ".join(cells)
            is_header = index == 0 and any(
                k in joined.lower() for k in ("phone", "number", "mobile", "contact")
            )
            if not is_header:
                result.invalid.append(joined[:80])
            continue

        phone_cell = next(c for c in cells if normalize_phone(c))
        phone = normalize_phone(phone_cell)
        assert phone is not None
        name = next((c for c in cells if c is not phone_cell and not normalize_phone(c)), "")
        if phone in seen:
            continue
        seen.add(phone)
        result.recipients.append((phone, name[:160]))
        if len(result.recipients) >= MAX_RECIPIENTS:
            break
    return result


class AddBroadcastRecipients:
    """Normalize, dedupe, and persist contacts onto a campaign."""

    def __init__(self, uow: UnitOfWork) -> None:
        self._uow = uow

    async def execute(
        self,
        tenant_id: TenantId,
        broadcast_id: uuid.UUID,
        *,
        structured: list[tuple[str, str]],
        text_blob: str,
    ) -> tuple[int, int, list[str]]:
        """Returns (added, duplicates, invalid)."""
        parsed = parse_contacts(text_blob)
        invalid = list(parsed.invalid)

        combined: dict[str, str] = {}
        for phone_raw, name in [*structured, *parsed.recipients]:
            phone = normalize_phone(phone_raw)
            if phone is None:
                invalid.append(phone_raw[:80])
                continue
            # First occurrence wins, but a later row with a name fills a blank.
            if phone not in combined or (not combined[phone] and name):
                combined[phone] = name

        candidates = list(combined.items())[:MAX_RECIPIENTS]
        if not candidates:
            return 0, 0, invalid

        recipients = [
            BroadcastRecipient(
                broadcast_id=broadcast_id,
                tenant_id=tenant_id,
                phone_number=phone,
                display_name=name,
            )
            for phone, name in candidates
        ]

        async with self._uow as uow:
            uow.set_tenant_scope(tenant_id)
            added = await uow.broadcast_recipients.add_many(recipients)
            broadcast = await uow.broadcasts.get(tenant_id, broadcast_id)
            if broadcast is not None:
                all_recipients = await uow.broadcast_recipients.list_for_broadcast(broadcast_id)
                broadcast.recompute_counts(all_recipients)
                await uow.broadcasts.update(broadcast)
            await uow.commit()

        return added, len(candidates) - added, invalid


class SendBroadcast:
    """Work a campaign's pending queue until it is empty, paused, or stopped."""

    def __init__(self, uow: UnitOfWork, whatsapp_sender, status_callback_url: str = "") -> None:
        self._uow = uow
        self._sender = whatsapp_sender
        self._status_callback_url = status_callback_url

    async def execute(self, tenant_id: TenantId, broadcast_id: uuid.UUID) -> int:
        """Returns how many messages were sent in this run."""
        sent_total = 0
        while True:
            async with self._uow as uow:
                uow.set_tenant_scope(tenant_id)
                broadcast = await uow.broadcasts.get(tenant_id, broadcast_id)
                if broadcast is None or not broadcast.accepts_sends():
                    return sent_total
                channel = await uow.whatsapp_channels.get(
                    tenant_id, broadcast.whatsapp_channel_id
                )
                if channel is None:
                    log.warning("broadcast.channel_missing", broadcast_id=str(broadcast_id))
                    broadcast.complete()
                    await uow.broadcasts.update(broadcast)
                    await uow.commit()
                    return sent_total
                batch = await uow.broadcast_recipients.claim_pending(broadcast_id, BATCH_SIZE)
                if not batch:
                    # Nothing left to send — close the campaign out.
                    all_recipients = await uow.broadcast_recipients.list_for_broadcast(
                        broadcast_id
                    )
                    broadcast.recompute_counts(all_recipients)
                    if broadcast.is_finished(all_recipients):
                        broadcast.complete()
                    await uow.broadcasts.update(broadcast)
                    await uow.commit()
                    return sent_total

                for recipient in batch:
                    await self._send_one(uow, broadcast, channel, recipient)
                    sent_total += 1
                    await asyncio.sleep(INTER_SEND_DELAY_SECONDS)

                all_recipients = await uow.broadcast_recipients.list_for_broadcast(broadcast_id)
                broadcast.recompute_counts(all_recipients)
                await uow.broadcasts.update(broadcast)
                await uow.commit()

    async def _send_one(self, uow, broadcast: Broadcast, channel, recipient) -> None:
        body = broadcast.render_message(recipient)
        ok, message_sid, error = await self._sender.send(
            account_sid=channel.twilio_account_sid,
            auth_token=channel.twilio_auth_token,
            from_number=channel.phone_number,
            to_number=recipient.phone_number,
            body=body,
            status_callback=self._status_callback_url,
        )
        if not ok:
            recipient.mark_failed(error)
            await uow.broadcast_recipients.update(recipient)
            return

        # Give the recipient a session + WhatsApp conversation now, so their
        # reply lands in an existing thread rather than opening a second one.
        session_id = await self._ensure_conversation(uow, broadcast, channel, recipient)
        recipient.session_id = session_id
        recipient.mark_sent(message_sid)
        await uow.broadcast_recipients.update(recipient)

        # Record the outbound message so the Chat Log shows the campaign's
        # opening line as the first turn of the conversation.
        await uow.chats.add_message(
            Message(
                session_id=session_id,
                tenant_id=broadcast.tenant_id,
                role=MessageRole.ASSISTANT,
                content=body,
            )
        )

    async def _ensure_conversation(self, uow, broadcast: Broadcast, channel, recipient):
        """Reuse the recipient's existing WhatsApp conversation if they have one
        (a returning contact keeps their history), otherwise create it."""
        from src.application.ports.repositories import WhatsAppConversation

        existing = await uow.whatsapp_conversations.get(channel.id, recipient.phone_number)
        if existing is not None:
            return existing.session_id

        session = ChatSession(
            tenant_id=broadcast.tenant_id,
            chatbot_id=broadcast.chatbot_id,
            title=recipient.display_name or recipient.phone_number,
        )
        await uow.chats.add_session(session)
        await uow.whatsapp_conversations.add(
            WhatsAppConversation(
                whatsapp_channel_id=channel.id,
                phone_number=recipient.phone_number,
                session_id=session.id,
            )
        )
        await uow.flush()
        return session.id
