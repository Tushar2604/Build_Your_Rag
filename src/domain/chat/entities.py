"""Chat session and message aggregates."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum

from src.domain.shared.identifiers import (
    ChatbotId,
    DocumentId,
    MessageId,
    SessionId,
    TenantId,
    new_id,
)


class MessageRole(StrEnum):
    USER = "user"
    ASSISTANT = "assistant"


@dataclass
class Citation:
    """A reference back to a source chunk, surfaced with assistant answers."""

    document_id: DocumentId
    chunk_id: str
    ordinal: int
    score: float
    snippet: str


@dataclass
class Message:
    session_id: SessionId
    tenant_id: TenantId
    role: MessageRole
    content: str
    id: MessageId = field(default_factory=lambda: MessageId(new_id()))
    citations: list[Citation] = field(default_factory=list)
    tokens_used: int = 0
    # Which LLM backend produced this answer (None for user messages and for
    # answers persisted before provider tracking existed). Powers the analytics
    # "was a bad day a silent failover?" slice.
    provider: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass
class ChatSession:
    tenant_id: TenantId
    chatbot_id: ChatbotId
    id: SessionId = field(default_factory=lambda: SessionId(new_id()))
    title: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
