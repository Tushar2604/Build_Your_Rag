"""In-process event bus.

At free-tier scale events are dispatched in-process: every event is written to
the audit log, and named handlers run inline. The `EventBus` port is the seam
that lets this become a real broker (NATS/Kafka/QStash) later with no change to
the domain or use cases.
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from dataclasses import asdict, is_dataclass

import structlog

from src.domain.shared.events import DomainEvent
from src.infrastructure.persistence import models as m
from src.infrastructure.persistence.database import get_sessionmaker

log = structlog.get_logger(__name__)

Handler = Callable[[DomainEvent], Awaitable[None]]


def _serialize(event: DomainEvent) -> dict:
    raw = asdict(event) if is_dataclass(event) else {}
    return {k: (str(v) if isinstance(v, uuid.UUID) else v) for k, v in raw.items()}


class InProcessEventBus:
    def __init__(self) -> None:
        self._handlers: dict[str, list[Handler]] = {}

    def subscribe(self, event_name: str, handler: Handler) -> None:
        self._handlers.setdefault(event_name, []).append(handler)

    async def publish(self, event: object) -> None:
        if not isinstance(event, DomainEvent):
            return
        await self._persist_audit(event)
        log.info("event.published", event_name=event.name, tenant_id=str(event.tenant_id))
        for handler in self._handlers.get(event.name, []):
            try:
                await handler(event)
            except Exception:  # noqa: BLE001 - one handler must not break others
                log.exception("event.handler_failed", event_name=event.name)

    async def _persist_audit(self, event: DomainEvent) -> None:
        payload = {
            k: v
            for k, v in _serialize(event).items()
            if k not in {"tenant_id", "occurred_at", "event_id"}
        }
        sm = get_sessionmaker()
        async with sm() as session:
            session.add(
                m.AuditEventModel(
                    id=uuid.uuid4(),
                    tenant_id=event.tenant_id,
                    name=event.name,
                    payload=payload,
                    occurred_at=event.occurred_at,
                )
            )
            await session.commit()
