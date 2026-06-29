"""Unit tests for the chat aggregate: MessageRole, Citation, Message, ChatSession."""

from __future__ import annotations

import uuid
from datetime import datetime

from src.domain.chat.entities import (
    ChatSession,
    Citation,
    Message,
    MessageRole,
)
from src.domain.shared.identifiers import (
    ChatbotId,
    DocumentId,
    SessionId,
    TenantId,
    new_id,
)


# --- MessageRole ---
def test_message_role_values() -> None:
    assert MessageRole.USER == "user"
    assert MessageRole.ASSISTANT == "assistant"
    assert set(MessageRole) == {MessageRole.USER, MessageRole.ASSISTANT}


# --- Citation ---
def test_citation_fields() -> None:
    did = DocumentId(new_id())
    c = Citation(document_id=did, chunk_id="ch1", ordinal=1, score=0.87, snippet="text")
    assert c.document_id is did
    assert c.chunk_id == "ch1"
    assert c.ordinal == 1
    assert c.score == 0.87
    assert c.snippet == "text"


# --- Message ---
def test_message_defaults() -> None:
    msg = Message(
        session_id=SessionId(new_id()),
        tenant_id=TenantId(new_id()),
        role=MessageRole.USER,
        content="hi",
    )
    assert msg.citations == []
    assert msg.tokens_used == 0
    assert isinstance(msg.id, uuid.UUID)
    assert isinstance(msg.created_at, datetime)


def test_message_independent_citation_lists() -> None:
    base = {
        "session_id": SessionId(new_id()),
        "tenant_id": TenantId(new_id()),
        "role": MessageRole.ASSISTANT,
        "content": "x",
    }
    a = Message(**base)
    b = Message(**base)
    a.citations.append(
        Citation(document_id=DocumentId(new_id()), chunk_id="c", ordinal=0,
                 score=1.0, snippet="s")
    )
    assert b.citations == []  # default_factory, not shared mutable default


def test_assistant_message_with_citations() -> None:
    cit = Citation(document_id=DocumentId(new_id()), chunk_id="c", ordinal=0,
                   score=0.5, snippet="s")
    msg = Message(
        session_id=SessionId(new_id()),
        tenant_id=TenantId(new_id()),
        role=MessageRole.ASSISTANT,
        content="answer",
        citations=[cit],
        tokens_used=120,
    )
    assert msg.citations == [cit]
    assert msg.tokens_used == 120


# --- ChatSession ---
def test_chat_session_defaults() -> None:
    s = ChatSession(tenant_id=TenantId(new_id()), chatbot_id=ChatbotId(new_id()))
    assert s.title is None
    assert isinstance(s.id, uuid.UUID)
    assert isinstance(s.created_at, datetime)
