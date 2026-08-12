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
    # --- WhatsApp attachment (all None for ordinary text) ---
    # `media_kind` is the discriminator the inbox filters on; the storage key
    # points at R2 or local disk behind `container.storage`, never a public URL.
    media_kind: str | None = None
    media_mime_type: str | None = None
    media_filename: str | None = None
    media_storage_key: str | None = None
    media_size_bytes: int | None = None
    # WhatsApp's own id, so a socket redelivery after reconnect is recognised
    # rather than stored twice.
    provider_message_id: str | None = None

    def has_media(self) -> bool:
        return bool(self.media_kind)


@dataclass
class ChatSession:
    tenant_id: TenantId
    chatbot_id: ChatbotId
    id: SessionId = field(default_factory=lambda: SessionId(new_id()))
    title: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
