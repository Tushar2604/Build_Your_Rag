"""Repository ports (Repository Pattern).

These are the seams between the application core and persistence. Use cases
depend only on these Protocols; the infrastructure layer provides SQLAlchemy
implementations. Every method is tenant-scoped — isolation is enforced here and
again by Postgres RLS as a backstop.
"""

from __future__ import annotations

import secrets
import uuid
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import Protocol, runtime_checkable

from src.domain.broadcast.entities import Broadcast, BroadcastRecipient
from src.domain.chat.entities import ChatSession, Message
from src.domain.chatbot.entities import Chatbot
from src.domain.document.entities import Chunk, Document
from src.domain.integration.entities import TenantIntegration
from src.domain.interview.batch_entities import BatchCandidate, InterviewBatch
from src.domain.interview.entities import Interview
from src.domain.postcall.entities import PostCallConfig, PostCallDelivery
from src.domain.support.entities import IssueReport
from src.domain.voice.entities import VoiceProfile
from src.domain.whatsapp_web.entities import WhatsAppWebSession
from src.domain.shared.identifiers import (
    BatchCandidateId,
    ChatbotId,
    DocumentId,
    InterviewBatchId,
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
    async def set_password_hash(self, user_id: UserId, password_hash: str) -> None: ...
    async def list_for_tenant(self, tenant_id: TenantId) -> list[User]: ...


@runtime_checkable
class ApiKeyRepository(Protocol):
    async def add(self, key: ApiKey) -> None: ...
    async def get_by_hash(self, key_hash: str) -> ApiKey | None: ...
    async def list_for_tenant(self, tenant_id: TenantId) -> list[ApiKey]: ...


def generate_invite_token() -> str:
    """An unguessable invite token — safe to embed in an emailed link,
    analogous to an interview's access_token or a chatbot's publishable key."""
    return secrets.token_urlsafe(24)


@dataclass
class TenantInvite:
    """An Owner/Admin's invitation for a teammate to join their tenant with a
    chosen role. The teammate has no account yet — `token` is emailed as a
    link; possessing it is what lets them set their own password and create
    their User row. `expires_at` is set by the inviting use case (a fixed
    window from creation), not defaulted here."""

    tenant_id: TenantId
    email: str
    role: str  # Role value ("admin" | "member" | "viewer") chosen by the inviter
    expires_at: datetime
    id: uuid.UUID = field(default_factory=new_id)
    token: str = field(default_factory=generate_invite_token)
    status: str = "pending"  # "pending" | "accepted"
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))


@runtime_checkable
class TenantInviteRepository(Protocol):
    async def add(self, invite: TenantInvite) -> None: ...
    async def get_by_token(self, token: str) -> TenantInvite | None: ...
    async def list_for_tenant(self, tenant_id: TenantId) -> list[TenantInvite]: ...
    async def mark_accepted(self, invite: TenantInvite) -> None: ...


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
    async def delete(self, tenant_id: TenantId, chatbot_id: ChatbotId) -> None: ...
    async def list_for_tenant(self, tenant_id: TenantId) -> list[Chatbot]: ...


@runtime_checkable
class ChatRepository(Protocol):
    async def add_session(self, session: ChatSession) -> None: ...
    async def get_session(
        self, tenant_id: TenantId, session_id: SessionId
    ) -> ChatSession | None: ...
    async def add_message(self, message: Message) -> None: ...
    async def list_messages(
        self,
        tenant_id: TenantId,
        session_id: SessionId,
        *,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[Message]: ...
    async def add_messages(self, messages: list[Message]) -> None: ...
    async def existing_provider_ids(
        self, tenant_id: TenantId, session_id: SessionId, provider_ids: list[str]
    ) -> set[str]: ...
    async def count_messages(self, tenant_id: TenantId, session_id: SessionId) -> int: ...
    async def message_exists(
        self, tenant_id: TenantId, session_id: SessionId, provider_message_id: str
    ) -> bool: ...
    async def assign_chatbot(
        self,
        tenant_id: TenantId,
        session_ids: list[SessionId],
        chatbot_id: ChatbotId | None,
    ) -> int: ...


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


@runtime_checkable
class InterviewBatchRepository(Protocol):
    async def add(self, batch: InterviewBatch) -> None: ...
    async def get(self, tenant_id: TenantId, batch_id: InterviewBatchId) -> InterviewBatch | None: ...
    async def update(self, batch: InterviewBatch) -> None: ...
    async def list_for_tenant(self, tenant_id: TenantId) -> list[InterviewBatch]: ...
    async def increment_counts(
        self, tenant_id: TenantId, batch_id: InterviewBatchId, *, total: int = 0, sent: int = 0, failed: int = 0
    ) -> None:
        """Atomic SQL-level increment — candidates are processed with bounded
        concurrency, so a read-modify-write here would lose updates."""
        ...


@runtime_checkable
class BatchCandidateRepository(Protocol):
    async def add(self, candidate: BatchCandidate) -> None: ...
    async def add_many(self, candidates: list[BatchCandidate]) -> None: ...
    async def get(
        self, tenant_id: TenantId, candidate_id: BatchCandidateId
    ) -> BatchCandidate | None: ...
    async def update(self, candidate: BatchCandidate) -> None: ...
    async def list_for_batch(self, tenant_id: TenantId, batch_id: InterviewBatchId) -> list[BatchCandidate]: ...


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


@dataclass
class OAuthConnection:
    """One tenant's consent to one OAuth provider.

    The generic form of GoogleOAuthConnection above, which is now just this
    record with `provider` pinned to "google_calendar" — kept as its own type so
    interview scheduling, which only ever means the calendar, doesn't have to
    name a provider on every call.
    """

    tenant_id: TenantId
    provider: str
    access_token: str
    expires_at: datetime
    # Empty when the vendor issued none. The connection works until the access
    # token expires, then needs re-consent.
    refresh_token: str = ""
    scope: str = ""
    # "Connected as …" — display only.
    account_label: str = ""
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))


@runtime_checkable
class OAuthConnectionRepository(Protocol):
    async def get(self, tenant_id: TenantId, provider: str) -> OAuthConnection | None: ...
    async def list_for_tenant(self, tenant_id: TenantId) -> list[OAuthConnection]: ...
    async def upsert(self, connection: OAuthConnection) -> None: ...
    async def delete(self, tenant_id: TenantId, provider: str) -> None: ...


@dataclass
class WhatsAppChannel:
    """A chatbot deployed to WhatsApp via Twilio. 1:1 with a chatbot — one
    WhatsApp number serves exactly one chatbot. Credentials are per-channel
    (entered by the admin when connecting), not an operator .env concern."""

    tenant_id: TenantId
    chatbot_id: ChatbotId
    phone_number: str  # E.164, no "whatsapp:" prefix, e.g. "+14155238886"
    twilio_account_sid: str
    twilio_auth_token: str
    id: uuid.UUID = field(default_factory=new_id)
    status: str = "active"
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))


@runtime_checkable
class WhatsAppChannelRepository(Protocol):
    async def add(self, channel: WhatsAppChannel) -> None: ...
    async def get(self, tenant_id: TenantId, channel_id: uuid.UUID) -> WhatsAppChannel | None: ...
    async def get_by_chatbot(
        self, tenant_id: TenantId, chatbot_id: ChatbotId
    ) -> WhatsAppChannel | None: ...
    async def get_by_phone_number(self, phone_number: str) -> WhatsAppChannel | None:
        """Resolve by the Twilio number that received the inbound message —
        NOT tenant-scoped (Twilio's webhook carries no tenant context),
        mirroring ChatbotRepository.get_by_public_key."""
        ...
    async def list_for_tenant(self, tenant_id: TenantId) -> list[WhatsAppChannel]: ...
    async def delete(self, tenant_id: TenantId, channel_id: uuid.UUID) -> None: ...


@dataclass
class WhatsAppConversation:
    """Maps one WhatsApp sender to a persistent ChatSession, so a phone
    number gets the same multi-turn memory as the web widget."""

    whatsapp_channel_id: uuid.UUID
    phone_number: str  # the external sender's number
    session_id: SessionId
    # Owning tenant. Added in 0022: the table used to be scoped only through its
    # channel, which the inbox cannot rely on because it queries this table
    # directly. Defaulted so existing constructor calls keep working; the
    # inbound paths set it explicitly.
    tenant_id: TenantId | None = None
    # False for announce-only campaigns: the reply is recorded, not answered.
    # Also what the inbox flips to hand a conversation to a human.
    auto_reply: bool = True
    # --- Denormalized for the thread list (one query, not one per thread) ---
    display_name: str = ""
    last_message_at: datetime | None = None
    last_message_preview: str = ""
    unread_count: int = 0
    has_attachment: bool = False
    id: uuid.UUID = field(default_factory=new_id)
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def note_message(self, *, preview: str, has_media: bool, inbound: bool) -> None:
        """Fold a newly stored message into the list metadata.

        Unread counts only inbound messages — an assistant answer or an operator
        reply is not something the operator needs to be told about.
        """
        self.last_message_at = datetime.now(UTC)
        self.last_message_preview = (preview or "").strip()[:300]
        if has_media:
            self.has_attachment = True
        if inbound:
            self.unread_count += 1
        self.updated_at = datetime.now(UTC)

    def mark_read(self) -> None:
        self.unread_count = 0
        self.updated_at = datetime.now(UTC)

    def set_auto_reply(self, enabled: bool) -> None:
        self.auto_reply = enabled
        self.updated_at = datetime.now(UTC)


@runtime_checkable
class WhatsAppConversationRepository(Protocol):
    async def get(
        self, whatsapp_channel_id: uuid.UUID, phone_number: str
    ) -> WhatsAppConversation | None: ...
    async def add(self, conversation: WhatsAppConversation) -> None: ...
    async def update(self, conversation: WhatsAppConversation) -> None: ...
    async def get_by_id(
        self, tenant_id: TenantId, conversation_id: uuid.UUID
    ) -> WhatsAppConversation | None: ...
    async def list_for_owner(
        self,
        tenant_id: TenantId,
        owner_id: uuid.UUID,
        *,
        search: str = "",
        has_attachment: bool | None = None,
        unread_only: bool = False,
        auto_reply: bool | None = None,
        limit: int = 30,
        offset: int = 0,
    ) -> list[WhatsAppConversation]: ...
    async def count_for_owner(
        self,
        tenant_id: TenantId,
        owner_id: uuid.UUID,
        *,
        search: str = "",
        has_attachment: bool | None = None,
        unread_only: bool = False,
        auto_reply: bool | None = None,
    ) -> int: ...


@runtime_checkable
class PostCallConfigRepository(Protocol):
    async def add(self, config: PostCallConfig) -> None: ...
    async def get(
        self, tenant_id: TenantId, config_id: uuid.UUID
    ) -> PostCallConfig | None: ...
    async def list_for_chatbot(
        self, tenant_id: TenantId, chatbot_id: ChatbotId
    ) -> list[PostCallConfig]: ...
    async def update(self, config: PostCallConfig) -> None: ...
    async def delete(self, tenant_id: TenantId, config_id: uuid.UUID) -> None: ...


@runtime_checkable
class PostCallDeliveryRepository(Protocol):
    async def claim(self, delivery: PostCallDelivery) -> bool:
        """Reserve (config, session); False if already dispatched. See impl."""
        ...

    async def finish(self, delivery: PostCallDelivery) -> None: ...
    async def list_for_chatbot(
        self, tenant_id: TenantId, chatbot_id: ChatbotId, limit: int = 50
    ) -> list[PostCallDelivery]: ...


@runtime_checkable
class BroadcastRepository(Protocol):
    async def add(self, broadcast: Broadcast) -> None: ...
    async def get(self, tenant_id: TenantId, broadcast_id: uuid.UUID) -> Broadcast | None: ...
    async def get_unscoped(self, broadcast_id: uuid.UUID) -> Broadcast | None: ...
    async def list_for_tenant(self, tenant_id: TenantId) -> list[Broadcast]: ...
    async def list_active(self) -> list[Broadcast]: ...
    async def update(self, broadcast: Broadcast) -> None: ...
    async def delete(self, tenant_id: TenantId, broadcast_id: uuid.UUID) -> None: ...


@runtime_checkable
class BroadcastRecipientRepository(Protocol):
    async def add_many(self, recipients: list[BroadcastRecipient]) -> int: ...
    async def get(
        self, tenant_id: TenantId, recipient_id: uuid.UUID
    ) -> BroadcastRecipient | None: ...
    async def get_by_provider_message_id(
        self, provider_message_id: str
    ) -> BroadcastRecipient | None: ...
    async def get_by_session(self, session_id: SessionId) -> BroadcastRecipient | None: ...
    async def list_for_broadcast(
        self,
        broadcast_id: uuid.UUID,
        *,
        status: str | None = None,
        search: str | None = None,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[BroadcastRecipient]: ...
    async def count_for_broadcast(
        self, broadcast_id: uuid.UUID, *, status: str | None = None, search: str | None = None
    ) -> int: ...
    async def claim_pending(
        self, broadcast_id: uuid.UUID, limit: int
    ) -> list[BroadcastRecipient]: ...
    async def update(self, recipient: BroadcastRecipient) -> None: ...
    async def reset_failed(self, broadcast_id: uuid.UUID) -> int: ...


@runtime_checkable
class TenantIntegrationRepository(Protocol):
    async def upsert(self, integration: TenantIntegration) -> None: ...
    async def get(
        self, tenant_id: TenantId, integration_id: str
    ) -> TenantIntegration | None: ...
    async def list_for_tenant(self, tenant_id: TenantId) -> list[TenantIntegration]: ...
    async def delete(self, tenant_id: TenantId, integration_id: str) -> None: ...


@runtime_checkable
class IssueReportRepository(Protocol):
    async def add(self, report: IssueReport) -> None: ...
    async def get(self, tenant_id: TenantId, report_id: uuid.UUID) -> IssueReport | None: ...
    async def list_for_tenant(
        self, tenant_id: TenantId, limit: int = 100
    ) -> list[IssueReport]: ...
    async def mark_email_sent(self, report_id: uuid.UUID, sent: bool) -> None: ...


@runtime_checkable
class VoiceProfileRepository(Protocol):
    async def add(self, profile: VoiceProfile) -> None: ...
    async def get(self, tenant_id: TenantId, profile_id: uuid.UUID) -> VoiceProfile | None: ...
    async def list_for_tenant(self, tenant_id: TenantId) -> list[VoiceProfile]: ...
    async def update(self, profile: VoiceProfile) -> None: ...
    async def delete(self, tenant_id: TenantId, profile_id: uuid.UUID) -> None: ...


@runtime_checkable
class WhatsAppWebSessionRepository(Protocol):
    async def add(self, ws: WhatsAppWebSession) -> None: ...
    async def get(
        self, tenant_id: TenantId, session_id: uuid.UUID
    ) -> WhatsAppWebSession | None: ...
    async def get_unscoped(self, session_id: uuid.UUID) -> WhatsAppWebSession | None: ...
    async def list_for_tenant(self, tenant_id: TenantId) -> list[WhatsAppWebSession]: ...
    async def update(self, ws: WhatsAppWebSession) -> None: ...
    async def delete(self, tenant_id: TenantId, session_id: uuid.UUID) -> None: ...


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
    interview_batches: InterviewBatchRepository
    batch_candidates: BatchCandidateRepository
    tenant_invites: TenantInviteRepository
    google_connections: GoogleConnectionRepository
    oauth_connections: OAuthConnectionRepository
    whatsapp_channels: WhatsAppChannelRepository
    whatsapp_conversations: WhatsAppConversationRepository
    post_call_configs: PostCallConfigRepository
    post_call_deliveries: PostCallDeliveryRepository
    broadcasts: BroadcastRepository
    broadcast_recipients: BroadcastRecipientRepository
    tenant_integrations: TenantIntegrationRepository
    issue_reports: IssueReportRepository
    voice_profiles: VoiceProfileRepository
    whatsapp_web_sessions: WhatsAppWebSessionRepository

    async def __aenter__(self) -> UnitOfWork: ...
    async def __aexit__(self, *args: object) -> None: ...
    async def commit(self) -> None: ...
    async def flush(self) -> None: ...
    async def rollback(self) -> None: ...
    def collect_event(self, event: object) -> None: ...
    def set_tenant_scope(self, tenant_id: uuid.UUID | None) -> None:
        """Bind the RLS session variable for this transaction."""
        ...
