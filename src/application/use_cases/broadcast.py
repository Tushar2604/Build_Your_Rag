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
from src.domain.shared.phone import canonical_phone

log = structlog.get_logger(__name__)

# Twilio throttles WhatsApp sends; a short gap between messages keeps a large
# campaign from tripping rate limits and failing recipients for no good reason.
INTER_SEND_DELAY_SECONDS = 0.35


@dataclass
class ParsedContacts:
    recipients: list[tuple[str, str]] = field(default_factory=list)  # (phone, name)
    invalid: list[str] = field(default_factory=list)
    # Numbers that appeared more than once. Reported rather than silently
    # collapsed so a list that looks short is explained, not just wrong.
    duplicates: list[str] = field(default_factory=list)


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
            result.duplicates.append(phone)
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

    def __init__(
        self,
        uow: UnitOfWork,
        whatsapp_sender,
        status_callback_url: str = "",
        bridge=None,
        cloud_sender=None,
        cloud_api_version: str = "v21.0",
    ) -> None:
        self._uow = uow
        self._sender = whatsapp_sender
        # Meta's Cloud API, used when the campaign's channel is a `cloud` one.
        # None means those campaigns report that it is unavailable rather than
        # sending through Twilio with credentials the channel does not have.
        self._cloud_sender = cloud_sender
        self._cloud_api_version = cloud_api_version
        self._status_callback_url = status_callback_url
        # The Node sidecar that owns QR-linked personal accounts. Only needed
        # for `sender_kind == "personal"`; None simply makes those campaigns
        # report that the bridge is unavailable rather than crashing.
        self._bridge = bridge

    async def execute(self, tenant_id: TenantId, broadcast_id: uuid.UUID) -> int:
        """Returns how many messages were sent in this run.

        One recipient per transaction, committed immediately after that
        recipient's send — not a whole claimed batch committed at the end.
        The WhatsApp send itself is irreversible (the bridge/Twilio has
        already handed it to the phone) but the bookkeeping that records it
        (`mark_sent`, the conversation, the outbound message row) used to be
        deferred, uncommitted, until an entire batch of up to 20 recipients
        finished. Anything that killed the process in between — an
        exception two recipients later, a redeploy landing mid-sweep on a
        host that restarts often — rolled the whole batch back on
        `SqlAlchemyUnitOfWork.__aexit__`, leaving already-delivered
        recipients stuck at "pending" with no record they were ever
        messaged, and a resume would message them again. Committing per
        recipient shrinks that window to one recipient instead of a batch.
        """
        sent_total = 0
        while True:
            async with self._uow as uow:
                uow.set_tenant_scope(tenant_id)
                broadcast = await uow.broadcasts.get(tenant_id, broadcast_id)
                if broadcast is None or not broadcast.accepts_sends():
                    return sent_total
                # A campaign sends from a Cloud API number or a linked personal
                # account. Only the former has Twilio credentials to look up.
                channel = None
                if broadcast.sender_kind == "cloud_api":
                    channel = await uow.whatsapp_channels.get(
                        tenant_id, broadcast.whatsapp_channel_id
                    )
                    if channel is None:
                        log.warning("broadcast.channel_missing", broadcast_id=str(broadcast_id))
                        broadcast.complete()
                        await uow.broadcasts.update(broadcast)
                        await uow.commit()
                        return sent_total
                elif broadcast.whatsapp_session_id is None:
                    log.warning("broadcast.session_missing", broadcast_id=str(broadcast_id))
                    broadcast.complete()
                    await uow.broadcasts.update(broadcast)
                    await uow.commit()
                    return sent_total

                claimed = await uow.broadcast_recipients.claim_pending(broadcast_id, 1)
                if not claimed:
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

                recipient = claimed[0]
                await self._send_one(uow, broadcast, channel, recipient)
                broadcast.record_send_outcome(recipient.status != "failed")
                await uow.broadcasts.update(broadcast)
                await uow.commit()

            sent_total += 1
            await asyncio.sleep(INTER_SEND_DELAY_SECONDS)

    async def _deliver(self, broadcast: Broadcast, channel, recipient, body: str):
        """Hand one message to whichever transport this campaign sends through.

        Returns the same `(ok, provider_message_id, error)` shape either way, so
        the bookkeeping below does not care which one ran. The personal bridge
        has no per-message id to give back — it is a socket, not an API with
        delivery receipts — so its campaigns simply never advance past `sent`.
        """
        if broadcast.sender_kind == "cloud_api":
            # `cloud_api` here means "a business number" — the campaign's own
            # vocabulary, older than there being two vendors behind it. Which
            # vendor is a fact about the channel, not about the campaign.
            if getattr(channel, "provider", "twilio") == "cloud":
                if self._cloud_sender is None:
                    return False, "", "The WhatsApp Cloud API sender is not configured."
                # No status_callback: Meta reports delivery on the same webhook
                # as inbound messages, so there is no second URL to hand it.
                return await self._cloud_sender.send(
                    phone_number_id=channel.phone_number_id,
                    access_token=channel.access_token,
                    to_number=recipient.phone_number,
                    body=body,
                    api_version=self._cloud_api_version,
                )
            return await self._sender.send(
                account_sid=channel.twilio_account_sid,
                auth_token=channel.twilio_auth_token,
                from_number=channel.phone_number,
                to_number=recipient.phone_number,
                body=body,
                status_callback=self._status_callback_url,
            )

        if self._bridge is None or not self._bridge.enabled:
            return False, "", "The WhatsApp bridge is not configured on this server."
        jid = f"{recipient.phone_number.lstrip('+')}@s.whatsapp.net"
        ok, error = await self._bridge.send_text(
            str(broadcast.whatsapp_session_id), jid, body
        )
        return ok, "", error

    async def _send_one(self, uow, broadcast: Broadcast, channel, recipient) -> None:
        body = broadcast.render_message(recipient)
        ok, message_sid, error = await self._deliver(broadcast, channel, recipient, body)
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
        (a returning contact keeps their history), otherwise create it.

        The conversation is created for both modes — an announce-only campaign
        still wants the outbound message in the log, and still wants to count a
        reply — but `auto_reply` decides whether the assistant answers.
        """
        from src.application.ports.repositories import WhatsAppConversation

        # The owning id is the channel for Cloud API and the linked session for
        # a personal account; the column holds either (see migration 0021).
        owner_id = broadcast.sender_id
        # Canonicalised so a recipient who later replies is recognised as the
        # contact this thread already belongs to, rather than opening a second
        # one under whatever shape the socket reports them in.
        phone = canonical_phone(recipient.phone_number)
        existing = await uow.whatsapp_conversations.get(owner_id, phone)
        if existing is not None:
            # The opening message has just gone out on an existing thread, so
            # the follow-up clock starts here too — a returning contact who
            # ignores this campaign is exactly as worth nudging as a new one.
            if broadcast.replies_are_answered():
                existing.start_waiting()
                await uow.whatsapp_conversations.update(existing)
            return existing.session_id

        session = ChatSession(
            tenant_id=broadcast.tenant_id,
            chatbot_id=broadcast.chatbot_id,
            title=recipient.display_name or recipient.phone_number,
        )
        await uow.chats.add_session(session)
        conversation = WhatsAppConversation(
            whatsapp_channel_id=owner_id,
            phone_number=phone,
            session_id=session.id,
            tenant_id=broadcast.tenant_id,
            auto_reply=broadcast.replies_are_answered(),
        )
        # Only a campaign whose replies are answered follows up. An
        # announce-only broadcast is a notice, not a conversation, and nudging
        # someone about one would be the assistant speaking out of turn.
        if broadcast.replies_are_answered():
            conversation.start_waiting()
        await uow.whatsapp_conversations.add(conversation)
        await uow.flush()
        return session.id
