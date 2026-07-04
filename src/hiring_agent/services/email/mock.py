"""MockEmailSender — records messages instead of delivering them.

No SMTP, no credentials, no network. Every 'sent' message is appended to an
in-memory outbox (a bounded ring buffer) so it can be inspected in tests or a
debug view. This is the adapter a real SMTP/API sender will replace.
"""

from __future__ import annotations

from collections import deque
from uuid import uuid4

import structlog

from src.hiring_agent.services.email.base import SendReceipt
from src.hiring_agent.types.email import EmailMessage

log = structlog.get_logger(__name__)

_OUTBOX_MAX = 200


class MockEmailSender:
    name = "mock"

    def __init__(self) -> None:
        self.outbox: deque[EmailMessage] = deque(maxlen=_OUTBOX_MAX)

    async def send(self, message: EmailMessage) -> SendReceipt:
        self.outbox.append(message)
        message_id = f"mock-email-{uuid4().hex[:12]}"
        log.info(
            "email.mock.sent",
            to=message.to,
            template=str(message.template),
            subject=message.subject,
            message_id=message_id,
        )
        return SendReceipt(message_id=message_id, status="sent", provider=self.name)

    def recent(self, limit: int = 20) -> list[EmailMessage]:
        return list(self.outbox)[-limit:]
