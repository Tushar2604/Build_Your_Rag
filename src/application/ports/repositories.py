"""Repository ports (Repository Pattern).

These are the seams between the application core and persistence. Use cases
depend only on these Protocols; the infrastructure layer provides SQLAlchemy
implementations. Every method is tenant-scoped — isolation is enforced here and
again by Postgres RLS as a backstop.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import Protocol, runtime_checkable

from src.domain.chat.entities import ChatSession, Message
from src.domain.chatbot.entities import Chatbot
from src.domain.document.entities import Chunk, Document
from src.domain.interview.entities import Interview
from src.domain.shared.identifiers import (
    ChatbotId,
    DocumentId,
    InterviewId,
    MessageId,
    SessionId,
    TenantId,
    UserId,
    new_id,
)
from src.domain.tenant.entities import ApiKey, Tenant, User


@runtime_checkable
class TenantRepository(Protocol):
    async def add(self, tenant: Tenant) -> None: ...
    async def get(self, tenant_id: TenantId) -> Tenant | None: ...
    async def get_by_slug(self, slug: str) -> Tenant | None: ...


@runtime_checkable
class UserRepository(Protocol):
    async def add(self, user: User) -> None: ...
    async def get(self, user_id: UserId) -> User | None: ...
    async def get_by_email(self, email: str) -> User | None: ...


@runtime_checkable
class ApiKeyRepository(Protocol):
    async def add(self, key: ApiKey) -> None: ...
    async def get_by_hash(self, key_hash: str) -> ApiKey | None: ...
    async def list_for_tenant(self, tenant_id: TenantId) -> list[ApiKey]: ...


@runtime_checkable
class DocumentRepository(Protocol):
    async def add(self, document: Document) -> None: ...
    async def get(self, tenant_id: TenantId, document_id: DocumentId) -> Document | None: ...
    async def update(self, document: Document) -> None: ...
    async def delete(self, tenant_id: TenantId, document_id: DocumentId) -> None: ...
    async def list_for_tenant(self, tenant_id: TenantId) -> list[Document]: ...
    async def count_for_tenant(self, tenant_id: TenantId) -> int: ...
    async def list_resumable(self) -> list[Document]:
        """Non-terminal documents to resume after a process restart/sleep."""
        ...


@runtime_checkable
class ChunkRepository(Protocol):
    """Vector store port, backed by pgvector."""

    async def add_many(self, chunks: list[Chunk], embeddings: list[list[float]]) -> None: ...
    async def delete_for_document(self, tenant_id: TenantId, document_id: DocumentId) -> None: ...
    async def list_for_document(
        self, tenant_id: TenantId, document_id: DocumentId
    ) -> list[Chunk]:
        """All chunks for one document, in ordinal order — reconstructs full
        text. Used where a small, fixed document set (e.g. one resume + one
        job description) should be passed as complete context rather than
        top-k retrieved."""
        ...
    async def search(
        self,
        tenant_id: TenantId,
        query_embedding: list[float],
        top_k: int,
        document_ids: list[DocumentId] | None = None,
        min_score: float = 0.0,
    ) -> list[tuple[Chunk, float]]:
        """Return (chunk, similarity) pairs, tenant-filtered."""
        ...


@runtime_checkable
class ChatbotRepository(Protocol):
    async def add(self, chatbot: Chatbot) -> None: ...
    async def get(self, tenant_id: TenantId, chatbot_id: ChatbotId) -> Chatbot | None: ...
    async def get_public(self, chatbot_id: ChatbotId) -> Chatbot | None: ...
    async def get_by_public_key(self, public_key: str) -> Chatbot | None: ...
    async def update(self, chatbot: Chatbot) -> None: ...
    async def list_for_tenant(self, tenant_id: TenantId) -> list[Chatbot]: ...


@runtime_checkable
class ChatRepository(Protocol):
    async def add_session(self, session: ChatSession) -> None: ...
    async def get_session(
        self, tenant_id: TenantId, session_id: SessionId
    ) -> ChatSession | None: ...
    async def add_message(self, message: Message) -> None: ...
    async def list_messages(self, tenant_id: TenantId, session_id: SessionId) -> list[Message]: ...


@runtime_checkable
class UsageRepository(Protocol):
    """Per-tenant daily token accounting (replaces Redis at free-tier scale)."""

    async def tokens_used_today(self, tenant_id: TenantId) -> int: ...
    async def add_tokens(self, tenant_id: TenantId, tokens: int) -> None: ...


@dataclass
class ChatbotDailyStat:
    """One day of answer-quality proxies for a chatbot, derived entirely from
    persisted assistant messages (citations + tokens) — no extra instrumentation.
    `avg_top_score` is averaged only over answers that retrieved something, so it
    measures retrieval *strength*; `no_context_rate` measures retrieval *misses*.
    """

    day: date
    answers: int
    avg_top_score: float | None  # None on days where nothing was ever retrieved
    avg_citations: float
    no_context_rate: float  # share of answers with zero retrieved chunks
    refusal_rate: float  # share matching the canonical "not in documents" refusal
    avg_tokens: float


@dataclass
class ProviderStat:
    """Answer counts + quality grouped by the LLM backend that served them — the
    'was a bad day a silent failover?' slice."""

    provider: str | None
    answers: int
    avg_top_score: float | None
    avg_tokens: float


@runtime_checkable
class AnalyticsRepository(Protocol):
    """Read-only aggregate queries over chat history. Tenant-scoped like every
    other repository; never touches the request/answer path."""

    async def chatbot_daily(
        self, tenant_id: TenantId, chatbot_id: ChatbotId, since: datetime
    ) -> list[ChatbotDailyStat]: ...

    async def chatbot_provider_mix(
        self, tenant_id: TenantId, chatbot_id: ChatbotId, since: datetime
    ) -> list[ProviderStat]: ...


@dataclass
class RequestLog:
    """The per-request evaluation record. One per ask, written success OR failure.
    Deterministic eval fields (no_context, refused, max_score, latency) are filled
    inline; a heavier groundedness score can be attached later by an eval worker."""

    tenant_id: TenantId
    chatbot_id: ChatbotId
    session_id: SessionId
    query: str
    status: str = "ok"  # 'ok' | 'error'
    num_retrieved: int = 0
    max_score: float | None = None
    no_context: bool = False
    refused: bool = False
    answer: str | None = None
    provider: str | None = None
    model: str | None = None
    tokens_used: int = 0
    latency_ms: int = 0
    error: str | None = None
    message_id: MessageId | None = None
    retrieved: list[dict] = field(default_factory=list)
    id: uuid.UUID = field(default_factory=new_id)
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))


@runtime_checkable
class RequestLogRepository(Protocol):
    """Append-only per-request log. Writing must never raise into the answer
    path — a logging failure cannot break a user's chat."""

    async def add(self, log: RequestLog) -> None: ...
    async def list_for_chatbot(
        self, tenant_id: TenantId, chatbot_id: ChatbotId, limit: int = 50
    ) -> list[RequestLog]: ...


@runtime_checkable
class InterviewRepository(Protocol):
    async def add(self, interview: Interview) -> None: ...
    async def get(self, tenant_id: TenantId, interview_id: InterviewId) -> Interview | None: ...
    async def get_by_token(self, access_token: str) -> Interview | None:
        """Resolve by the candidate's opaque access token — NOT tenant-scoped
        (the candidate has no tenant context), mirroring
        ChatbotRepository.get_by_public_key."""
        ...
    async def update(self, interview: Interview) -> None: ...
    async def list_for_tenant(self, tenant_id: TenantId) -> list[Interview]: ...


@dataclass
class GoogleOAuthConnection:
    """One tenant's 'Connect Google Calendar' tokens. Absent for a tenant =
    not connected; scheduling an interview simply skips the calendar step."""

    tenant_id: TenantId
    access_token: str
    refresh_token: str
    expires_at: datetime
    scope: str = ""
    connected_email: str = ""
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))


@runtime_checkable
class GoogleConnectionRepository(Protocol):
    async def get(self, tenant_id: TenantId) -> GoogleOAuthConnection | None: ...
    async def upsert(self, connection: GoogleOAuthConnection) -> None: ...
    async def delete(self, tenant_id: TenantId) -> None: ...


@runtime_checkable
class UnitOfWork(Protocol):
    """Transaction boundary. A use case opens one UoW, does its work through the
    repositories, then commits. Collected domain events are dispatched on commit.
    """

    tenants: TenantRepository
    users: UserRepository
    api_keys: ApiKeyRepository
    documents: DocumentRepository
    chunks: ChunkRepository
    chatbots: ChatbotRepository
    chats: ChatRepository
    usage: UsageRepository
    analytics: AnalyticsRepository
    request_logs: RequestLogRepository
    interviews: InterviewRepository
    google_connections: GoogleConnectionRepository

    async def __aenter__(self) -> UnitOfWork: ...
    async def __aexit__(self, *args: object) -> None: ...
    async def commit(self) -> None: ...
    async def flush(self) -> None: ...
    async def rollback(self) -> None: ...
    def collect_event(self, event: object) -> None: ...
    def set_tenant_scope(self, tenant_id: uuid.UUID | None) -> None:
        """Bind the RLS session variable for this transaction."""
        ...
