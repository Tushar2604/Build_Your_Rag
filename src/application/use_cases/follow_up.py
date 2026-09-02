"""Nudge contacts who have gone quiet, then let them go.

The ladder, per conversation: we send something, and if nothing comes back
within the window, a nudge goes out. Two nudges, then a sign-off that says we
will be here whenever they are — and the thread stops asking. Anything the
contact sends at any point resets the whole thing (see
`WhatsAppConversation.note_message`), so a reply always wins over a pending
nudge.

Why a sweep rather than a timer per conversation: this process restarts on
every deploy and sleeps when idle, and an in-memory timer would forget every
pending follow-up on the way down. The schedule lives on the row
(`awaiting_reply_since`), so a sweep that wakes up late finds the thread
overdue and handles it then — the worst a restart costs is a nudge arriving
a minute or two after the window rather than never.

Everything sent here is persisted as an ordinary assistant message on the same
session, so it is part of the conversation's memory: the inbox and the
Candidates profile show it, and the next real answer the assistant generates
reads it as prior context and will not repeat itself.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import structlog

from src.application.ports.repositories import UnitOfWork, WhatsAppConversation
from src.domain.chat.entities import Message, MessageRole

log = structlog.get_logger(__name__)

# One nudge, then a firmer one, then the sign-off. Indexed by how many have
# already gone out, so the wording escalates rather than repeating verbatim —
# the same sentence twice reads like a broken bot.
FOLLOW_UP_MESSAGES = (
    "Just checking in — did you get a chance to see my last message?",
    "Still happy to answer any questions whenever you have a moment.",
)

# What we leave behind when nobody answers. Deliberately warm and final: it
# closes the loop without asking for anything, so the last thing in the thread
# is an open door rather than an unanswered question.
SIGN_OFF_MESSAGE = (
    "Looks like you're offline at the moment — no problem at all. "
    "Message me whenever you're free and we'll pick this up from here."
)


class SendFollowUps:
    """One pass over every conversation that has gone quiet for too long."""

    def __init__(
        self,
        uow: UnitOfWork,
        *,
        bridge=None,
        whatsapp_sender=None,
        after: timedelta,
        max_follow_ups: int,
        batch_limit: int = 50,
    ) -> None:
        self._uow = uow
        self._bridge = bridge
        self._sender = whatsapp_sender
        self._after = after
        self._max = max_follow_ups
        self._batch_limit = batch_limit

    async def execute(self, *, now: datetime | None = None) -> int:
        """Returns how many follow-ups were sent."""
        moment = now or datetime.now(UTC)
        cutoff = moment - self._after

        async with self._uow as uow:
            due = await uow.whatsapp_conversations.list_due_follow_ups(
                cutoff=cutoff, max_follow_ups=self._max, limit=self._batch_limit
            )

        sent = 0
        for conversation in due:
            if await self._send_one(conversation, moment):
                sent += 1
        return sent

    async def _send_one(self, conversation: WhatsAppConversation, moment: datetime) -> bool:
        """Claim this conversation's nudge and send it — atomically enough
        that two overlapping sweeps cannot both do it.

        The advisory lock around the whole tick (`_sweep_lease` in the API app)
        is supposed to make that impossible on its own, but it protects a
        *tick*, not a conversation — and this codebase has observed, in
        production, the same nudge delivered to the same contact two and three
        times within a couple of seconds of each other, which is a single-tick
        timescale, not a sweep-interval one. Rather than depend on diagnosing
        exactly how two sends started (another process, a retried tick,
        anything else that can end up running this loop twice), this makes the
        one moment that actually matters — deciding to send, and sending —
        safe under real concurrency on its own terms: everything from the
        fresh re-check through the send happens inside one transaction holding
        a row lock (`lock_for_follow_up`), so a second caller racing on the
        same conversation gets `None` back and does nothing, before either of
        them has sent a thing.
        """
        async with self._uow as uow:
            uow.set_tenant_scope(conversation.tenant_id)
            fresh = await uow.whatsapp_conversations.lock_for_follow_up(
                conversation.tenant_id, conversation.id
            )
            if fresh is None:
                # Gone, or another caller has the lock right now — either way
                # this is not this call's to send.
                return False
            # Re-checked against a row fetched *inside* this lock, not the one
            # `execute()` read a moment ago: the whole point of the lock is
            # that nothing about this conversation can be trusted from before
            # it was taken. A reply that arrived in between is the case that
            # matters most — nudging someone who has just answered is the one
            # outcome this feature must never produce.
            if not fresh.follow_up_due(after=self._after, max_follow_ups=self._max, now=moment):
                return False

            final = fresh.is_final_follow_up(max_follow_ups=self._max)
            body = (
                SIGN_OFF_MESSAGE
                if final
                else FOLLOW_UP_MESSAGES[min(fresh.followups_sent, len(FOLLOW_UP_MESSAGES) - 1)]
            )

            ok, error = await self._deliver(uow, fresh, body)
            if not ok:
                # Left as-is so the next sweep retries. A number that is
                # unreachable for good keeps failing, which is noisy in the
                # logs but never silently drops someone who was only briefly
                # offline. The row lock releases when this transaction ends
                # either way, so the retry is not blocked by this attempt.
                log.warning(
                    "followup.send_failed",
                    conversation_id=str(fresh.id),
                    tenant_id=str(fresh.tenant_id),
                    error=error,
                )
                return False

            await uow.chats.add_message(
                Message(
                    session_id=fresh.session_id,
                    tenant_id=fresh.tenant_id,
                    role=MessageRole.ASSISTANT,
                    content=body,
                    # Distinguishes an automated nudge from a generated answer
                    # in the thread, the same way operator/device replies are.
                    provider="whatsapp:follow_up",
                )
            )
            fresh.note_message(preview=body, has_media=False, inbound=False)
            # After note_message, which would otherwise restart the clock on a
            # thread we have just finished signing off.
            fresh.record_follow_up(final=final, now=moment)
            await uow.whatsapp_conversations.update(fresh)
            await uow.commit()

        log.info(
            "followup.sent",
            conversation_id=str(fresh.id),
            tenant_id=str(fresh.tenant_id),
            attempt=fresh.followups_sent,
            final=final,
        )
        return True

    async def _deliver(self, uow, conversation: WhatsAppConversation, body: str):  # type: ignore[no-untyped-def]
        """Send through whichever transport owns this conversation.

        Takes the caller's own open `uow` rather than starting a fresh one:
        `_send_one` is holding a row lock for the duration of this call
        precisely so the send happens under it, and a second, separate
        transaction here would look up channel credentials outside that
        protection for no reason.

        `whatsapp_channel_id` is polymorphic — a linked personal session or a
        Cloud API channel — so the owner is resolved by lookup rather than
        assumed, exactly as the campaign sender does.
        """
        session = await uow.whatsapp_web_sessions.get(
            conversation.tenant_id, conversation.whatsapp_channel_id
        )
        channel = None
        if session is None:
            channel = await uow.whatsapp_channels.get(
                conversation.tenant_id, conversation.whatsapp_channel_id
            )

        if session is not None:
            if self._bridge is None or not self._bridge.enabled:
                return False, "The WhatsApp bridge is not configured on this server."
            if session.status != "linked":
                return False, "This WhatsApp number is not currently linked."
            jid = f"{conversation.phone_number.lstrip('+')}@s.whatsapp.net"
            return await self._bridge.send_text(str(session.id), jid, body)

        if channel is None:
            return False, "The WhatsApp number this conversation came in on is gone."
        if self._sender is None:
            return False, "No WhatsApp sender is configured on this server."
        ok, _sid, error = await self._sender.send(
            account_sid=channel.twilio_account_sid,
            auth_token=channel.twilio_auth_token,
            from_number=channel.phone_number,
            to_number=conversation.phone_number,
            body=body,
        )
        return ok, error
