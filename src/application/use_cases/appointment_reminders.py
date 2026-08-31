"""Remind people about the appointment they are about to have.

A sweep rather than a timer per appointment, for the same reason the follow-up
ladder is one: this process restarts on every deploy and sleeps when idle, and
an in-memory timer would forget every pending reminder on the way down. The
schedule lives on the row — `starts_at` and `reminder_sent_at` — so a sweep
that wakes up late finds the appointment due and handles it then.

Two rules do most of the work here, and both exist because a reminder is a
message to a real person that cannot be unsent:

  * **Never twice.** `reminder_sent_at` is written after a successful send, and
    the sweep only ever reads rows where it is NULL. Two workers ticking at
    once are additionally kept apart by the advisory lock the loop takes.
  * **Never late.** An appointment that has already started is skipped
    entirely. A sweep that ran an hour behind — a redeploy, a sleeping
    free-tier host — would otherwise tell someone about a slot they are already
    sitting in, which reads as a system that does not know what time it is.

The message is delivered on the contact's existing WhatsApp thread where they
have one, so it lands in the shared inbox and becomes part of the conversation
the assistant will read on the next turn — rather than arriving from nowhere
and being invisible to whoever picks the thread up next.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import structlog

from src.application.ports.repositories import UnitOfWork
from src.domain.chat.entities import Message, MessageRole
from src.domain.scheduling.entities import Appointment
from src.domain.shared.phone import canonical_phone

log = structlog.get_logger(__name__)

# The provider tag on the stored message. Distinguishes an automated reminder
# from an assistant answer and from an operator's own reply, so the inbox can
# say which it was — see `_author_of` in the whatsapp_web router.
REMINDER_PROVIDER = "system:reminder"


def _in_zone(moment: datetime, zone: str) -> datetime:
    """Render an instant in the zone the customer was quoted in.

    Falling back to the stored instant rather than raising: a bad timezone
    string on one appointment must not stop the sweep for everyone else, and a
    time in the wrong zone is still more useful than no reminder at all.
    """
    if not zone:
        return moment
    try:
        return moment.astimezone(ZoneInfo(zone))
    except (ZoneInfoNotFoundError, ValueError):
        return moment


def build_reminder(appointment: Appointment, *, service_name: str, location_name: str) -> str:
    """The message itself.

    States the actual clock time rather than "in 30 minutes". The sweep is
    allowed to fire for an appointment booked inside the lead window, and for
    that person "in 30 minutes" would simply be false — where the real time is
    correct however late or early the message happens to land.
    """
    zone = appointment.customer_timezone or appointment.timezone
    local = _in_zone(appointment.starts_at, zone)
    # `%-I` would be neater but it is a glibc extension that raises on Windows,
    # which this also runs on. Zero-padded plus a trim works everywhere.
    when = local.strftime("%I:%M %p").lstrip("0")

    what = service_name or "your appointment"
    where = f" at {location_name}" if location_name else ""
    name = (appointment.customer_name or "").split(" ")[0]
    hello = f"Hi {name}, " if name else "Hi, "
    return (
        f"{hello}a quick reminder about {what}{where} today at {when}. "
        "See you shortly — reply here if you need to change it."
    )


class SendAppointmentReminders:
    def __init__(
        self,
        uow: UnitOfWork,
        *,
        bridge=None,
        whatsapp_sender=None,
        lead: timedelta,
        batch_limit: int = 100,
    ) -> None:
        self._uow = uow
        self._bridge = bridge
        self._sender = whatsapp_sender
        self._lead = lead
        self._batch_limit = batch_limit

    async def execute(self, *, now: datetime | None = None) -> int:
        """Returns how many reminders were sent."""
        moment = now or datetime.now(UTC)

        async with self._uow as uow:
            due = await uow.appointments.list_due_reminders(
                now=moment, lead=self._lead, limit=self._batch_limit
            )

        sent = 0
        for appointment in due:
            # Re-checked against the entity rather than trusting the query, so
            # the rule lives in one place and the SQL is only an index hint.
            if not appointment.needs_reminder(now=moment, lead=self._lead):
                continue
            if await self._send_one(appointment, moment):
                sent += 1
        return sent

    async def _send_one(self, appointment: Appointment, moment: datetime) -> bool:
        if not appointment.customer_phone:
            # Nothing to send to. Marked as handled so the sweep stops
            # reconsidering it every minute until the appointment passes —
            # a walk-in booked at the desk has no phone number and never will.
            await self._mark(appointment, moment)
            log.info(
                "appointment.reminder.skipped",
                appointment_id=str(appointment.id),
                reason="no_phone",
            )
            return False

        async with self._uow as uow:
            uow.set_tenant_scope(appointment.tenant_id)
            service = await uow.services.get(appointment.tenant_id, appointment.service_id)
            location = await uow.locations.get(appointment.tenant_id, appointment.location_id)
            # Matched on digits, not on the stored spelling — see
            # `domain.shared.phone`. Newest-active first, so a contact who has
            # written to two of the workspace's numbers is reminded on the one
            # they actually use.
            threads = await uow.whatsapp_conversations.threads_for_contact(
                appointment.tenant_id, appointment.customer_phone
            )
            conversation = threads[0] if threads else None

        body = build_reminder(
            appointment,
            service_name=service.name if service else "",
            location_name=location.name if location else "",
        )

        ok, error = await self._deliver(appointment, conversation, body)
        if not ok:
            # Left unmarked so the next tick retries. A bridge that is briefly
            # down should delay the reminder, not cancel it — and the
            # `starts_at > now` bound means retries stop by themselves once the
            # appointment begins, so this cannot loop forever.
            log.warning(
                "appointment.reminder.failed",
                appointment_id=str(appointment.id),
                error=error,
            )
            return False

        # Recorded on the thread so the reminder is part of the conversation:
        # visible in the inbox, and read as prior context by the next answer the
        # assistant generates, which stops it greeting someone it just messaged.
        if conversation is not None:
            async with self._uow as uow:
                uow.set_tenant_scope(appointment.tenant_id)
                await uow.chats.add_message(
                    Message(
                        session_id=conversation.session_id,
                        tenant_id=appointment.tenant_id,
                        role=MessageRole.ASSISTANT,
                        content=body,
                        provider=REMINDER_PROVIDER,
                    )
                )
                conversation.note_message(preview=body, has_media=False, inbound=False)
                await uow.whatsapp_conversations.update(conversation)
                await uow.commit()

        await self._mark(appointment, moment)
        log.info(
            "appointment.reminder.sent",
            appointment_id=str(appointment.id),
            tenant_id=str(appointment.tenant_id),
            starts_at=appointment.starts_at.isoformat(),
        )
        return True

    async def _mark(self, appointment: Appointment, moment: datetime) -> None:
        appointment.mark_reminded(now=moment)
        async with self._uow as uow:
            uow.set_tenant_scope(appointment.tenant_id)
            await uow.appointments.mark_reminder_sent(appointment)
            await uow.commit()

    async def _deliver(self, appointment: Appointment, conversation, body: str):
        """Send through whichever WhatsApp number owns this contact.

        Preference order, and the reason for it: the thread the customer
        already has, because a reminder arriving on the same number as every
        other message is the one that looks legitimate. Only if they have no
        thread do we fall back to any linked number the workspace has.
        """
        phone = canonical_phone(appointment.customer_phone)

        async with self._uow as uow:
            uow.set_tenant_scope(appointment.tenant_id)
            session = None
            channel = None
            if conversation is not None:
                session = await uow.whatsapp_web_sessions.get(
                    appointment.tenant_id, conversation.whatsapp_channel_id
                )
                if session is None:
                    channel = await uow.whatsapp_channels.get(
                        appointment.tenant_id, conversation.whatsapp_channel_id
                    )
            if session is None and channel is None:
                linked = [
                    ws
                    for ws in await uow.whatsapp_web_sessions.list_for_tenant(
                        appointment.tenant_id
                    )
                    if ws.status == "linked"
                ]
                session = linked[0] if linked else None

        if session is not None:
            if self._bridge is None or not self._bridge.enabled:
                return False, "The WhatsApp bridge is not configured on this server."
            if session.status != "linked":
                return False, "This WhatsApp number is not currently linked."
            jid = f"{phone.lstrip('+')}@s.whatsapp.net"
            return await self._bridge.send_text(str(session.id), jid, body)

        if channel is None:
            return False, "No WhatsApp number is connected to send the reminder from."
        if self._sender is None:
            return False, "No WhatsApp sender is configured on this server."
        ok, _sid, error = await self._sender.send(
            account_sid=channel.twilio_account_sid,
            auth_token=channel.twilio_auth_token,
            from_number=channel.phone_number,
            to_number=phone,
            body=body,
        )
        return ok, error
