"""Unit tests for strongly-typed identifiers and the id factory."""

from __future__ import annotations

import uuid

from src.domain.shared.identifiers import (
    ChatbotId,
    DocumentId,
    MessageId,
    SessionId,
    TenantId,
    UserId,
    new_id,
)


def test_new_id_returns_uuid() -> None:
    val = new_id()
    assert isinstance(val, uuid.UUID)
    assert val.version == 4


def test_new_id_is_unique() -> None:
    ids = {new_id() for _ in range(1000)}
    assert len(ids) == 1000


def test_newtype_aliases_are_identity_wrappers() -> None:
    # NewType is a runtime identity function: the wrapped value is unchanged,
    # the alias only adds static type distinction.
    raw = new_id()
    for alias in (TenantId, UserId, DocumentId, ChatbotId, SessionId, MessageId):
        assert alias(raw) is raw
