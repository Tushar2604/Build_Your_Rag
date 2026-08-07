"""Guard: the new use cases must consume a UnitOfWork *instance* via
`async with self._uow`, matching every other use case in the codebase.

Written after a real bug: these two were originally authored to take a factory
and call it (`self._uow_factory()`), while the routers passed an already-built
instance. Nothing caught it — the domain tests never touch a UoW and the app
still imported cleanly — so it would only have surfaced as a TypeError the first
time a campaign was started or a conversation ended.

The stub below is a context manager but is NOT callable, so factory-style usage
fails loudly here instead of in production.
"""

from __future__ import annotations

import asyncio
import uuid

import pytest
from src.application.use_cases.broadcast import AddBroadcastRecipients, SendBroadcast
from src.application.use_cases.post_call import DispatchPostCall
from src.domain.broadcast.entities import Broadcast, BroadcastRecipient
from src.domain.shared.identifiers import ChatbotId, SessionId, TenantId, new_id

TENANT = TenantId(new_id())
CHATBOT = ChatbotId(new_id())


class _Recipients:
    def __init__(self) -> None:
        self.rows: list[BroadcastRecipient] = []

    async def add_many(self, recipients: list[BroadcastRecipient]) -> int:
        # Mimics ON CONFLICT DO NOTHING on (broadcast_id, phone_number).
        existing = {r.phone_number for r in self.rows}
        fresh = [r for r in recipients if r.phone_number not in existing]
        self.rows.extend(fresh)
        return len(fresh)

    async def list_for_broadcast(self, broadcast_id, **kwargs) -> list[BroadcastRecipient]:
        return list(self.rows)

    async def claim_pending(self, broadcast_id, limit: int) -> list[BroadcastRecipient]:
        return [r for r in self.rows if r.status == "pending"][:limit]

    async def update(self, recipient: BroadcastRecipient) -> None:
        pass


class _Broadcasts:
    def __init__(self, broadcast: Broadcast | None) -> None:
        self.broadcast = broadcast
        self.updates = 0

    async def get(self, tenant_id, broadcast_id) -> Broadcast | None:
        return self.broadcast

    async def update(self, broadcast: Broadcast) -> None:
        self.updates += 1


class _Configs:
    async def list_for_chatbot(self, tenant_id, chatbot_id) -> list:
        return []


class _Chats:
    async def list_messages(self, tenant_id, session_id) -> list:
        return []


class _Chatbots:
    async def get(self, tenant_id, chatbot_id):
        return None


class _StubUow:
    """Supports `async with`, and is deliberately NOT callable."""

    def __init__(self, broadcast: Broadcast | None = None) -> None:
        self.entered = 0
        self.commits = 0
        self.scoped_to: TenantId | None = None
        self.broadcast_recipients = _Recipients()
        self.broadcasts = _Broadcasts(broadcast)
        self.post_call_configs = _Configs()
        self.chats = _Chats()
        self.chatbots = _Chatbots()

    async def __aenter__(self):
        self.entered += 1
        return self

    async def __aexit__(self, *args: object) -> None:
        return None

    def set_tenant_scope(self, tenant_id) -> None:
        self.scoped_to = tenant_id

    async def commit(self) -> None:
        self.commits += 1

    async def flush(self) -> None:
        pass


def _broadcast(**kwargs) -> Broadcast:
    base = {
        "tenant_id": TENANT,
        "chatbot_id": CHATBOT,
        "whatsapp_channel_id": new_id(),
        "name": "Campaign",
        "message_template": "Hi {{first_name}}",
    }
    return Broadcast(**{**base, **kwargs})


# --- The contract itself ---


def test_add_recipients_enters_the_uow_instance() -> None:
    uow = _StubUow(broadcast=_broadcast())
    added, duplicates, invalid = asyncio.run(
        AddBroadcastRecipients(uow).execute(
            TENANT,
            uuid.uuid4(),
            structured=[("+917502163963", "Mohammed")],
            text_blob="+971553752665, Aisha",
        )
    )
    assert uow.entered == 1, "the use case must `async with` the instance it was given"
    assert uow.commits == 1
    assert uow.scoped_to == TENANT
    assert (added, duplicates, invalid) == (2, 0, [])


def test_send_broadcast_enters_the_uow_instance() -> None:
    # A campaign that isn't sending returns immediately — enough to prove the
    # `async with` works without needing Twilio.
    uow = _StubUow(broadcast=_broadcast(status="paused"))
    sent = asyncio.run(SendBroadcast(uow, whatsapp_sender=None).execute(TENANT, uuid.uuid4()))
    assert uow.entered == 1
    assert sent == 0


def test_dispatch_post_call_enters_the_uow_instance() -> None:
    uow = _StubUow()
    result = asyncio.run(
        DispatchPostCall(uow, llm=None, webhook_sender=None, email_sender=None).execute(
            TENANT, CHATBOT, SessionId(new_id()), "completed"
        )
    )
    assert uow.entered == 1
    assert (result.dispatched, result.skipped) == (0, 0)


@pytest.mark.parametrize(
    "build",
    [
        lambda uow: AddBroadcastRecipients(uow),
        lambda uow: SendBroadcast(uow, whatsapp_sender=None),
        lambda uow: DispatchPostCall(uow, llm=None, webhook_sender=None, email_sender=None),
    ],
)
def test_use_cases_store_the_uow_under_the_conventional_name(build) -> None:
    # `_uow` (not `_uow_factory`) is what signals instance semantics to the next
    # person wiring one of these up.
    uow = _StubUow()
    assert getattr(build(uow), "_uow", None) is uow


# --- Behaviour the stub can still exercise ---


def test_add_recipients_dedupes_across_both_inputs() -> None:
    uow = _StubUow(broadcast=_broadcast())
    added, duplicates, _ = asyncio.run(
        AddBroadcastRecipients(uow).execute(
            TENANT,
            uuid.uuid4(),
            structured=[("+917502163963", "Mohammed")],
            text_blob="+91 75021 63963\n+971553752665",
        )
    )
    assert added == 2  # the repeated number collapses before it reaches the DB
    assert duplicates == 0


def test_add_recipients_reports_unusable_numbers() -> None:
    uow = _StubUow(broadcast=_broadcast())
    added, _, invalid = asyncio.run(
        AddBroadcastRecipients(uow).execute(
            TENANT, uuid.uuid4(), structured=[("555-1234", "Local")], text_blob=""
        )
    )
    assert added == 0
    assert invalid == ["555-1234"]


def test_add_recipients_recomputes_campaign_counts() -> None:
    broadcast = _broadcast()
    uow = _StubUow(broadcast=broadcast)
    asyncio.run(
        AddBroadcastRecipients(uow).execute(
            TENANT, broadcast.id, structured=[], text_blob="+917502163963\n+971553752665"
        )
    )
    assert broadcast.total_count == 2
    assert uow.broadcasts.updates == 1
