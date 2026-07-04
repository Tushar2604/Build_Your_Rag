"""Email sender port.

The seam between the send-email service and any delivery backend. The mock
adapter satisfies it now; an SMTP / SendGrid / SES adapter will satisfy the same
protocol later with no change to the service or tool.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from src.hiring_agent.types.email import EmailMessage


@dataclass(frozen=True)
class SendReceipt:
    message_id: str
    status: str  # sent | queued | failed
    provider: str


@runtime_checkable
class EmailSender(Protocol):
    name: str

    async def send(self, message: EmailMessage) -> SendReceipt:
        """Deliver a message and return a receipt."""
        ...
