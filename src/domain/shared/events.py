"""Domain events.

Aggregates record events that something meaningful happened. The application
layer collects and dispatches them after a use case commits, decoupling side
effects (webhooks, usage metering, audit) from core business logic.

At free-tier scale the dispatcher is a simple in-process bus; the same event
contract drops onto a real broker later without touching the domain.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime


@dataclass(frozen=True, kw_only=True)
class DomainEvent:
    """Base class for all domain events.

    Every event carries the tenant scope and a correlation id so it can be
    traced end-to-end through logs and (later) the message bus.
    """

    tenant_id: uuid.UUID
    occurred_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    event_id: uuid.UUID = field(default_factory=uuid.uuid4)

    @property
    def name(self) -> str:
        return self.__class__.__name__
