"""Unit tests for domain events.

Covers the base `DomainEvent` (defaults, frozen-ness, `name`) and every concrete
subclass across the tenant, document, and chat aggregates.
"""

from __future__ import annotations

import dataclasses
import uuid
from datetime import UTC, datetime

import pytest
from src.domain.chat.events import MessageAnswered
from src.domain.document.events import (
    DocumentIngested,
    DocumentIngestionFailed,
    DocumentUploaded,
)
from src.domain.shared.events import DomainEvent
from src.domain.shared.identifiers import new_id
from src.domain.tenant.events import QuotaExceeded, TenantProvisioned


def test_base_event_defaults_populate() -> None:
    tid = new_id()
    event = DomainEvent(tenant_id=tid)
    assert event.tenant_id is tid
    assert isinstance(event.event_id, uuid.UUID)
    assert isinstance(event.occurred_at, datetime)
    assert event.occurred_at.tzinfo is UTC


def test_base_event_name_is_class_name() -> None:
    assert DomainEvent(tenant_id=new_id()).name == "DomainEvent"


def test_event_ids_are_unique_per_instance() -> None:
    a = DomainEvent(tenant_id=new_id())
    b = DomainEvent(tenant_id=new_id())
    assert a.event_id != b.event_id


def test_event_is_frozen() -> None:
    event = DomainEvent(tenant_id=new_id())
    with pytest.raises(dataclasses.FrozenInstanceError):
        event.tenant_id = new_id()  # type: ignore[misc]


def test_event_is_keyword_only() -> None:
    # kw_only=True means positional construction is rejected.
    with pytest.raises(TypeError):
        DomainEvent(new_id())  # type: ignore[misc]


def test_tenant_provisioned() -> None:
    # Regression guard: the event field is `tenant_name`, not `name`, so it does
    # not collide with the inherited (setter-less) DomainEvent.name property.
    tid = new_id()
    e = TenantProvisioned(tenant_id=tid, tenant_name="Acme", owner_email="o@acme.com")
    assert e.name == "TenantProvisioned"  # inherited property = class name
    assert e.tenant_name == "Acme"
    assert e.owner_email == "o@acme.com"
    assert e.tenant_id is tid


def test_quota_exceeded() -> None:
    e = QuotaExceeded(tenant_id=new_id(), quota_kind="tokens", limit=200_000)
    assert e.name == "QuotaExceeded"
    assert e.quota_kind == "tokens"
    assert e.limit == 200_000


def test_document_uploaded() -> None:
    did = new_id()
    e = DocumentUploaded(tenant_id=new_id(), document_id=did, filename="a.pdf")
    assert e.name == "DocumentUploaded"
    assert e.document_id is did
    assert e.filename == "a.pdf"


def test_document_ingested() -> None:
    e = DocumentIngested(tenant_id=new_id(), document_id=new_id(), chunk_count=12)
    assert e.name == "DocumentIngested"
    assert e.chunk_count == 12


def test_document_ingestion_failed() -> None:
    e = DocumentIngestionFailed(tenant_id=new_id(), document_id=new_id(), reason="bad")
    assert e.name == "DocumentIngestionFailed"
    assert e.reason == "bad"


def test_message_answered() -> None:
    sid, cid = new_id(), new_id()
    e = MessageAnswered(
        tenant_id=new_id(),
        session_id=sid,
        chatbot_id=cid,
        tokens_used=42,
        provider="groq",
    )
    assert e.name == "MessageAnswered"
    assert e.session_id is sid
    assert e.chatbot_id is cid
    assert e.tokens_used == 42
    assert e.provider == "groq"


@pytest.mark.parametrize(
    "factory",
    [
        lambda: QuotaExceeded(tenant_id=new_id(), quota_kind="tokens", limit=1),
        lambda: DocumentUploaded(tenant_id=new_id(), document_id=new_id(), filename="f"),
        lambda: MessageAnswered(
            tenant_id=new_id(), session_id=new_id(), chatbot_id=new_id(),
            tokens_used=1, provider="p",
        ),
    ],
)
def test_subclasses_inherit_frozen(factory) -> None:  # type: ignore[no-untyped-def]
    event = factory()
    assert isinstance(event, DomainEvent)
    with pytest.raises(dataclasses.FrozenInstanceError):
        event.tokens_used = 9  # type: ignore[attr-defined]
