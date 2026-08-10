"""SQLAlchemy implementations of the repository ports.

Every query is explicitly filtered by tenant_id (primary isolation guard);
Postgres RLS provides defense-in-depth on top. The vector search uses pgvector
cosine distance computed inside Postgres — no separate vector service.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import delete, func, select, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.ports.repositories import (
    ChatbotDailyStat,
    GoogleOAuthConnection,
    OAuthConnection,
    ProviderStat,
    RequestLog,
    TenantInvite,
    WhatsAppChannel,
    WhatsAppConversation,
)
from src.domain.broadcast.entities import Broadcast, BroadcastRecipient
from src.domain.chat.entities import ChatSession, Message
from src.domain.chatbot.entities import Chatbot
from src.domain.document.entities import Chunk, Document, IngestionStatus
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
)
from src.domain.tenant.entities import ApiKey, Tenant, User
from src.infrastructure.persistence import mappers as map_
from src.infrastructure.persistence import models as m


class TenantRepositoryImpl:
    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    async def add(self, tenant: Tenant) -> None:
        self._s.add(
            m.TenantModel(
                id=tenant.id,
                name=tenant.name,
                slug=tenant.slug,
                daily_token_quota=tenant.daily_token_quota,
                max_documents=tenant.max_documents,
                is_active=tenant.is_active,
                created_at=tenant.created_at,
            )
        )

    async def get(self, tenant_id: TenantId) -> Tenant | None:
        row = await self._s.get(m.TenantModel, tenant_id)
        return map_.tenant_to_domain(row) if row else None

    async def get_by_slug(self, slug: str) -> Tenant | None:
        row = (
            await self._s.execute(select(m.TenantModel).where(m.TenantModel.slug == slug))
        ).scalar_one_or_none()
        return map_.tenant_to_domain(row) if row else None


class UserRepositoryImpl:
    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    async def add(self, user: User) -> None:
        self._s.add(
            m.UserModel(
                id=user.id,
                tenant_id=user.tenant_id,
                email=user.email,
                password_hash=user.password_hash,
                role=user.role.value,
                is_active=user.is_active,
                created_at=user.created_at,
            )
        )

    async def get(self, user_id: UserId) -> User | None:
        row = await self._s.get(m.UserModel, user_id)
        return map_.user_to_domain(row) if row else None

    async def get_by_email(self, email: str) -> User | None:
        row = (
            await self._s.execute(select(m.UserModel).where(m.UserModel.email == email))
        ).scalar_one_or_none()
        return map_.user_to_domain(row) if row else None

    async def list_for_tenant(self, tenant_id: TenantId) -> list[User]:
        rows = (
            await self._s.execute(
                select(m.UserModel)
                .where(m.UserModel.tenant_id == tenant_id)
                .order_by(m.UserModel.created_at.asc())
            )
        ).scalars().all()
        return [map_.user_to_domain(r) for r in rows]


class ApiKeyRepositoryImpl:
    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    async def add(self, key: ApiKey) -> None:
        self._s.add(
            m.ApiKeyModel(
                id=key.id,
                tenant_id=key.tenant_id,
                name=key.name,
                key_hash=key.key_hash,
                prefix=key.prefix,
                is_active=key.is_active,
                created_at=key.created_at,
            )
        )

    async def get_by_hash(self, key_hash: str) -> ApiKey | None:
        row = (
            await self._s.execute(
                select(m.ApiKeyModel).where(
                    m.ApiKeyModel.key_hash == key_hash, m.ApiKeyModel.is_active.is_(True)
                )
            )
        ).scalar_one_or_none()
        return map_.apikey_to_domain(row) if row else None

    async def list_for_tenant(self, tenant_id: TenantId) -> list[ApiKey]:
        rows = (
            await self._s.execute(
                select(m.ApiKeyModel).where(m.ApiKeyModel.tenant_id == tenant_id)
            )
        ).scalars()
        return [map_.apikey_to_domain(r) for r in rows]


class TenantInviteRepositoryImpl:
    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    async def add(self, invite: TenantInvite) -> None:
        self._s.add(
            m.TenantInviteModel(
                id=invite.id,
                tenant_id=invite.tenant_id,
                email=invite.email,
                role=invite.role,
                token=invite.token,
                status=invite.status,
                created_at=invite.created_at,
                expires_at=invite.expires_at,
            )
        )

    async def get_by_token(self, token: str) -> TenantInvite | None:
        row = (
            await self._s.execute(
                select(m.TenantInviteModel).where(m.TenantInviteModel.token == token)
            )
        ).scalar_one_or_none()
        return map_.tenant_invite_to_domain(row) if row else None

    async def list_for_tenant(self, tenant_id: TenantId) -> list[TenantInvite]:
        rows = (
            await self._s.execute(
                select(m.TenantInviteModel)
                .where(m.TenantInviteModel.tenant_id == tenant_id)
                .order_by(m.TenantInviteModel.created_at.desc())
            )
        ).scalars().all()
        return [map_.tenant_invite_to_domain(r) for r in rows]

    async def mark_accepted(self, invite: TenantInvite) -> None:
        row = await self._s.get(m.TenantInviteModel, invite.id)
        if row is not None:
            row.status = "accepted"


class DocumentRepositoryImpl:
    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    async def add(self, document: Document) -> None:
        self._s.add(
            m.DocumentModel(
                id=document.id,
                tenant_id=document.tenant_id,
                filename=document.filename,
                content_type=document.content_type,
                size_bytes=document.size_bytes,
                storage_key=document.storage_key,
                checksum=document.checksum,
                status=document.status.value,
                chunk_count=document.chunk_count,
                error=document.error,
            )
        )

    async def get(self, tenant_id: TenantId, document_id: DocumentId) -> Document | None:
        row = (
            await self._s.execute(
                select(m.DocumentModel).where(
                    m.DocumentModel.id == document_id,
                    m.DocumentModel.tenant_id == tenant_id,
                )
            )
        ).scalar_one_or_none()
        return map_.document_to_domain(row) if row else None

    async def update(self, document: Document) -> None:
        row = await self._s.get(m.DocumentModel, document.id)
        if row is None:
            return
        row.status = document.status.value
        row.chunk_count = document.chunk_count
        row.error = document.error
        row.checksum = document.checksum
        row.updated_at = document.updated_at

    async def delete(self, tenant_id: TenantId, document_id: DocumentId) -> None:
        await self._s.execute(
            delete(m.DocumentModel).where(
                m.DocumentModel.id == document_id,
                m.DocumentModel.tenant_id == tenant_id,
            )
        )

    async def list_for_tenant(self, tenant_id: TenantId) -> list[Document]:
        rows = (
            await self._s.execute(
                select(m.DocumentModel)
                .where(m.DocumentModel.tenant_id == tenant_id)
                .order_by(m.DocumentModel.created_at.desc())
            )
        ).scalars()
        return [map_.document_to_domain(r) for r in rows]

    async def count_for_tenant(self, tenant_id: TenantId) -> int:
        return (
            await self._s.execute(
                select(func.count())
                .select_from(m.DocumentModel)
                .where(m.DocumentModel.tenant_id == tenant_id)
            )
        ).scalar_one()

    async def list_resumable(self) -> list[Document]:
        # Non-terminal, non-pending docs left mid-pipeline by a restart.
        active = [
            IngestionStatus.UPLOADED.value,
            IngestionStatus.PARSING.value,
            IngestionStatus.CHUNKING.value,
            IngestionStatus.EMBEDDING.value,
        ]
        rows = (
            await self._s.execute(
                select(m.DocumentModel).where(m.DocumentModel.status.in_(active))
            )
        ).scalars()
        return [map_.document_to_domain(r) for r in rows]


class ChunkRepositoryImpl:
    """pgvector-backed vector store."""

    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    async def add_many(self, chunks: list[Chunk], embeddings: list[list[float]]) -> None:
        for chunk, vector in zip(chunks, embeddings, strict=True):
            self._s.add(
                m.ChunkModel(
                    id=uuid.UUID(chunk.id),
                    tenant_id=chunk.tenant_id,
                    document_id=chunk.document_id,
                    ordinal=chunk.ordinal,
                    text=chunk.text,
                    token_estimate=chunk.token_estimate,
                    embedding=vector,
                )
            )

    async def delete_for_document(
        self, tenant_id: TenantId, document_id: DocumentId
    ) -> None:
        await self._s.execute(
            delete(m.ChunkModel).where(
                m.ChunkModel.tenant_id == tenant_id,
                m.ChunkModel.document_id == document_id,
            )
        )

    async def list_for_document(self, tenant_id: TenantId, document_id: DocumentId) -> list[Chunk]:
        rows = (
            await self._s.execute(
                select(m.ChunkModel)
                .where(m.ChunkModel.tenant_id == tenant_id, m.ChunkModel.document_id == document_id)
                .order_by(m.ChunkModel.ordinal)
            )
        ).scalars()
        return [
            Chunk(
                id=str(row.id),
                tenant_id=TenantId(row.tenant_id),
                document_id=DocumentId(row.document_id),
                ordinal=row.ordinal,
                text=row.text,
                token_estimate=row.token_estimate,
            )
            for row in rows
        ]

    async def search(
        self,
        tenant_id: TenantId,
        query_embedding: list[float],
        top_k: int,
        document_ids: list[DocumentId] | None = None,
        min_score: float = 0.0,
    ) -> list[tuple[Chunk, float]]:
        import math

        stmt = select(m.ChunkModel).where(m.ChunkModel.tenant_id == tenant_id)
        # `None` and `[]` mean different things and must not be collapsed:
        # None = unscoped (search the whole tenant), [] = an assistant with an
        # empty knowledge base, which must retrieve nothing rather than
        # everything. `IN ()` yields no rows, which is exactly right.
        if document_ids is not None:
            stmt = stmt.where(m.ChunkModel.document_id.in_(document_ids))

        rows = (await self._s.execute(stmt)).scalars().all()

        def _cosine(a: list[float], b: list[float]) -> float:
            dot = sum(x * y for x, y in zip(a, b))
            mag = math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(x * x for x in b))
            return dot / mag if mag else 0.0

        scored = [
            (row, _cosine(query_embedding, row.embedding))
            for row in rows
            if row.embedding
        ]
        scored.sort(key=lambda t: t[1], reverse=True)

        results: list[tuple[Chunk, float]] = []
        for row, sim in scored[:top_k]:
            if sim < min_score:
                continue
            results.append((
                Chunk(
                    id=str(row.id),
                    tenant_id=TenantId(row.tenant_id),
                    document_id=DocumentId(row.document_id),
                    ordinal=row.ordinal,
                    text=row.text,
                    token_estimate=row.token_estimate,
                ),
                sim,
            ))
        return results


class ChatbotRepositoryImpl:
    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    async def add(self, chatbot: Chatbot) -> None:
        row = _chatbot_to_row(chatbot)
        self._s.add(row)
        # Flush so the sequence-assigned display_id comes back now rather
        # than after commit — the create response carries it, and the UI
        # shows it on the card the moment the assistant appears.
        await self._s.flush()
        chatbot.display_id = row.display_id

    async def get(self, tenant_id: TenantId, chatbot_id: ChatbotId) -> Chatbot | None:
        row = (
            await self._s.execute(
                select(m.ChatbotModel).where(
                    m.ChatbotModel.id == chatbot_id,
                    m.ChatbotModel.tenant_id == tenant_id,
                )
            )
        ).scalar_one_or_none()
        return map_.chatbot_to_domain(row) if row else None

    async def get_public(self, chatbot_id: ChatbotId) -> Chatbot | None:
        row = (
            await self._s.execute(
                select(m.ChatbotModel).where(
                    m.ChatbotModel.id == chatbot_id, m.ChatbotModel.is_public.is_(True)
                )
            )
        ).scalar_one_or_none()
        return map_.chatbot_to_domain(row) if row else None

    async def get_by_public_key(self, public_key: str) -> Chatbot | None:
        """Resolve a chatbot from its publishable key — intentionally NOT
        tenant-scoped (the widget caller has no tenant context). Only public
        bots are returned, so a key for a private bot resolves to nothing."""
        row = (
            await self._s.execute(
                select(m.ChatbotModel).where(
                    m.ChatbotModel.public_key == public_key,
                    m.ChatbotModel.is_public.is_(True),
                )
            )
        ).scalar_one_or_none()
        return map_.chatbot_to_domain(row) if row else None

    async def update(self, chatbot: Chatbot) -> None:
        row = await self._s.get(m.ChatbotModel, chatbot.id)
        if row is None:
            return
        row.name = chatbot.name
        row.channel = chatbot.channel
        row.system_prompt = chatbot.system_prompt
        row.flow_sections = map_.flow_sections_to_jsonb(chatbot.flow_sections)
        row.voice_profile_id = chatbot.voice_profile_id
        row.retrieval = map_.chatbot_retrieval_to_jsonb(chatbot.retrieval)
        row.assistant_config = map_.assistant_config_to_jsonb(chatbot.assistant)
        row.allowed_document_ids = [str(d) for d in chatbot.allowed_document_ids]
        row.is_public = chatbot.is_public
        row.public_key = chatbot.public_key
        row.allowed_origins = list(chatbot.allowed_origins)
        row.widget_config = map_.widget_config_to_jsonb(chatbot.widget)

    async def list_for_tenant(self, tenant_id: TenantId) -> list[Chatbot]:
        rows = (
            await self._s.execute(
                select(m.ChatbotModel).where(m.ChatbotModel.tenant_id == tenant_id)
            )
        ).scalars()
        return [map_.chatbot_to_domain(r) for r in rows]


def _chatbot_to_row(chatbot: Chatbot) -> m.ChatbotModel:
    return m.ChatbotModel(
        id=chatbot.id,
        tenant_id=chatbot.tenant_id,
        name=chatbot.name,
        channel=chatbot.channel,
        system_prompt=chatbot.system_prompt,
        flow_sections=map_.flow_sections_to_jsonb(chatbot.flow_sections),
        voice_profile_id=chatbot.voice_profile_id,
        retrieval=map_.chatbot_retrieval_to_jsonb(chatbot.retrieval),
        assistant_config=map_.assistant_config_to_jsonb(chatbot.assistant),
        allowed_document_ids=[str(d) for d in chatbot.allowed_document_ids],
        is_public=chatbot.is_public,
        public_key=chatbot.public_key,
        allowed_origins=list(chatbot.allowed_origins),
        widget_config=map_.widget_config_to_jsonb(chatbot.widget),
        created_at=chatbot.created_at,
    )


class ChatRepositoryImpl:
    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    async def add_session(self, session: ChatSession) -> None:
        self._s.add(
            m.ChatSessionModel(
                id=session.id,
                tenant_id=session.tenant_id,
                chatbot_id=session.chatbot_id,
                title=session.title,
                created_at=session.created_at,
            )
        )

    async def get_session(
        self, tenant_id: TenantId, session_id: SessionId
    ) -> ChatSession | None:
        row = (
            await self._s.execute(
                select(m.ChatSessionModel).where(
                    m.ChatSessionModel.id == session_id,
                    m.ChatSessionModel.tenant_id == tenant_id,
                )
            )
        ).scalar_one_or_none()
        return map_.session_to_domain(row) if row else None

    async def add_message(self, message: Message) -> None:
        self._s.add(
            m.ChatMessageModel(
                id=message.id,
                tenant_id=message.tenant_id,
                session_id=message.session_id,
                role=message.role.value,
                content=message.content,
                citations=map_.citations_to_jsonb(message.citations),
                tokens_used=message.tokens_used,
                provider=message.provider,
                created_at=message.created_at,
            )
        )

    async def list_messages(
        self, tenant_id: TenantId, session_id: SessionId
    ) -> list[Message]:
        rows = (
            await self._s.execute(
                select(m.ChatMessageModel)
                .where(
                    m.ChatMessageModel.tenant_id == tenant_id,
                    m.ChatMessageModel.session_id == session_id,
                )
                .order_by(m.ChatMessageModel.created_at.asc())
            )
        ).scalars()
        return [map_.message_to_domain(r) for r in rows]


class UsageRepositoryImpl:
    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    async def tokens_used_today(self, tenant_id: TenantId) -> int:
        today = datetime.now(UTC).date()
        val = (
            await self._s.execute(
                select(m.UsageCounterModel.tokens_used).where(
                    m.UsageCounterModel.tenant_id == tenant_id,
                    m.UsageCounterModel.day == today,
                )
            )
        ).scalar_one_or_none()
        return int(val or 0)

    async def add_tokens(self, tenant_id: TenantId, tokens: int) -> None:
        today = datetime.now(UTC).date()
        # Atomic upsert: insert-or-increment in a single statement.
        stmt = (
            pg_insert(m.UsageCounterModel)
            .values(id=uuid.uuid4(), tenant_id=tenant_id, day=today, tokens_used=tokens)
            .on_conflict_do_update(
                index_elements=["tenant_id", "day"],
                set_={"tokens_used": m.UsageCounterModel.tokens_used + tokens},
            )
        )
        await self._s.execute(stmt)


# The canonical off-topic redirect emitted by DEFAULT_SYSTEM_PROMPT.
# Heuristic (custom prompts may refuse differently); no_context_rate is the
# prompt-independent retrieval-miss signal, refusal_rate is the secondary one.
_REFUSAL_LIKE = "I'm here to help with our open roles and your application%"


class AnalyticsRepositoryImpl:
    """Aggregate reads over chat_messages joined to their chatbot. Raw SQL keeps
    the JSONB citation-score extraction readable; still tenant-filtered."""

    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    async def chatbot_daily(
        self, tenant_id: TenantId, chatbot_id: ChatbotId, since: datetime
    ) -> list[ChatbotDailyStat]:
        sql = text(
            """
            SELECT date_trunc('day', m.created_at)::date            AS day,
                   count(*)                                          AS answers,
                   avg((m.citations->0->>'score')::float)           AS avg_top_score,
                   avg(jsonb_array_length(m.citations))::float      AS avg_citations,
                   avg((jsonb_array_length(m.citations) = 0)::int)::float AS no_context_rate,
                   avg((m.content LIKE :refusal)::int)::float        AS refusal_rate,
                   avg(m.tokens_used)::float                         AS avg_tokens
            FROM chat_messages m
            JOIN chat_sessions s ON s.id = m.session_id
            WHERE m.tenant_id = :tid
              AND m.role = 'assistant'
              AND s.chatbot_id = :cid
              AND m.created_at >= :since
            GROUP BY 1
            ORDER BY 1
            """
        )
        rows = await self._s.execute(
            sql,
            {"tid": tenant_id, "cid": chatbot_id, "since": since, "refusal": _REFUSAL_LIKE},
        )
        return [
            ChatbotDailyStat(
                day=r.day,
                answers=r.answers,
                avg_top_score=r.avg_top_score,
                avg_citations=r.avg_citations or 0.0,
                no_context_rate=r.no_context_rate or 0.0,
                refusal_rate=r.refusal_rate or 0.0,
                avg_tokens=r.avg_tokens or 0.0,
            )
            for r in rows
        ]

    async def chatbot_provider_mix(
        self, tenant_id: TenantId, chatbot_id: ChatbotId, since: datetime
    ) -> list[ProviderStat]:
        sql = text(
            """
            SELECT m.provider                              AS provider,
                   count(*)                                AS answers,
                   avg((m.citations->0->>'score')::float)  AS avg_top_score,
                   avg(m.tokens_used)::float               AS avg_tokens
            FROM chat_messages m
            JOIN chat_sessions s ON s.id = m.session_id
            WHERE m.tenant_id = :tid
              AND m.role = 'assistant'
              AND s.chatbot_id = :cid
              AND m.created_at >= :since
            GROUP BY m.provider
            ORDER BY answers DESC
            """
        )
        rows = await self._s.execute(
            sql, {"tid": tenant_id, "cid": chatbot_id, "since": since}
        )
        return [
            ProviderStat(
                provider=r.provider,
                answers=r.answers,
                avg_top_score=r.avg_top_score,
                avg_tokens=r.avg_tokens or 0.0,
            )
            for r in rows
        ]


def _request_log_to_domain(row: m.RagRequestLogModel) -> RequestLog:
    return RequestLog(
        id=row.id,
        tenant_id=TenantId(row.tenant_id),
        chatbot_id=ChatbotId(row.chatbot_id),
        session_id=SessionId(row.session_id),
        message_id=MessageId(row.message_id) if row.message_id else None,
        query=row.query,
        retrieved=row.retrieved or [],
        num_retrieved=row.num_retrieved,
        max_score=row.max_score,
        no_context=row.no_context,
        refused=row.refused,
        answer=row.answer,
        provider=row.provider,
        model=row.model,
        tokens_used=row.tokens_used,
        status=row.status,
        error=row.error,
        latency_ms=row.latency_ms,
        created_at=row.created_at,
    )


class RequestLogRepositoryImpl:
    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    async def add(self, log: RequestLog) -> None:
        self._s.add(
            m.RagRequestLogModel(
                id=log.id,
                tenant_id=log.tenant_id,
                chatbot_id=log.chatbot_id,
                session_id=log.session_id,
                message_id=log.message_id,
                query=log.query,
                retrieved=log.retrieved,
                num_retrieved=log.num_retrieved,
                max_score=log.max_score,
                no_context=log.no_context,
                refused=log.refused,
                answer=log.answer,
                provider=log.provider,
                model=log.model,
                tokens_used=log.tokens_used,
                status=log.status,
                error=log.error,
                latency_ms=log.latency_ms,
                created_at=log.created_at,
            )
        )

    async def list_for_chatbot(
        self, tenant_id: TenantId, chatbot_id: ChatbotId, limit: int = 50
    ) -> list[RequestLog]:
        rows = (
            await self._s.execute(
                select(m.RagRequestLogModel)
                .where(
                    m.RagRequestLogModel.tenant_id == tenant_id,
                    m.RagRequestLogModel.chatbot_id == chatbot_id,
                )
                .order_by(m.RagRequestLogModel.created_at.desc())
                .limit(limit)
            )
        ).scalars()
        return [_request_log_to_domain(r) for r in rows]


class InterviewRepositoryImpl:
    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    async def add(self, interview: Interview) -> None:
        self._s.add(_interview_to_row(interview))

    async def get(self, tenant_id: TenantId, interview_id: InterviewId) -> Interview | None:
        row = (
            await self._s.execute(
                select(m.InterviewModel).where(
                    m.InterviewModel.id == interview_id,
                    m.InterviewModel.tenant_id == tenant_id,
                )
            )
        ).scalar_one_or_none()
        return map_.interview_to_domain(row) if row else None

    async def get_by_token(self, access_token: str) -> Interview | None:
        row = (
            await self._s.execute(
                select(m.InterviewModel).where(m.InterviewModel.access_token == access_token)
            )
        ).scalar_one_or_none()
        return map_.interview_to_domain(row) if row else None

    async def update(self, interview: Interview) -> None:
        row = await self._s.get(m.InterviewModel, interview.id)
        if row is None:
            return
        row.candidate_name = interview.candidate_name
        row.candidate_email = interview.candidate_email
        row.role_title = interview.role_title
        row.scheduled_at = interview.scheduled_at
        row.window_closes_at = interview.window_closes_at
        row.status = interview.status
        row.questions = list(interview.questions)
        row.transcript = map_.transcript_to_jsonb(interview.transcript)
        row.current_question_index = interview.current_question_index
        row.google_event_id = interview.google_event_id
        row.calendar_link = interview.calendar_link
        row.report_storage_key = interview.report_storage_key
        row.overall_score = interview.overall_score
        row.overall_verdict = interview.overall_verdict
        row.scores = map_.scores_to_jsonb(interview.scores)
        row.updated_at = datetime.now(UTC)

    async def list_for_tenant(self, tenant_id: TenantId) -> list[Interview]:
        rows = (
            await self._s.execute(
                select(m.InterviewModel)
                .where(m.InterviewModel.tenant_id == tenant_id)
                .order_by(m.InterviewModel.scheduled_at.desc())
            )
        ).scalars()
        return [map_.interview_to_domain(r) for r in rows]


def _interview_to_row(interview: Interview) -> m.InterviewModel:
    return m.InterviewModel(
        id=interview.id,
        tenant_id=interview.tenant_id,
        candidate_name=interview.candidate_name,
        candidate_email=interview.candidate_email,
        role_title=interview.role_title,
        job_document_id=interview.job_document_id,
        resume_document_id=interview.resume_document_id,
        scheduled_at=interview.scheduled_at,
        window_closes_at=interview.window_closes_at,
        status=interview.status,
        access_token=interview.access_token,
        questions=list(interview.questions),
        transcript=map_.transcript_to_jsonb(interview.transcript),
        current_question_index=interview.current_question_index,
        google_event_id=interview.google_event_id,
        calendar_link=interview.calendar_link,
        report_storage_key=interview.report_storage_key,
        overall_score=interview.overall_score,
        overall_verdict=interview.overall_verdict,
        scores=map_.scores_to_jsonb(interview.scores),
        created_at=interview.created_at,
        updated_at=interview.updated_at,
    )


class InterviewBatchRepositoryImpl:
    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    async def add(self, batch: InterviewBatch) -> None:
        self._s.add(
            m.InterviewBatchModel(
                id=batch.id,
                tenant_id=batch.tenant_id,
                role_title=batch.role_title,
                job_document_id=batch.job_document_id,
                window_opens_at=batch.window_opens_at,
                window_closes_at=batch.window_closes_at,
                custom_questions=list(batch.custom_questions),
                status=batch.status,
                total_count=batch.total_count,
                sent_count=batch.sent_count,
                failed_count=batch.failed_count,
                created_at=batch.created_at,
                updated_at=batch.updated_at,
            )
        )

    async def get(self, tenant_id: TenantId, batch_id: InterviewBatchId) -> InterviewBatch | None:
        row = (
            await self._s.execute(
                select(m.InterviewBatchModel).where(
                    m.InterviewBatchModel.id == batch_id,
                    m.InterviewBatchModel.tenant_id == tenant_id,
                )
            )
        ).scalar_one_or_none()
        return map_.interview_batch_to_domain(row) if row else None

    async def update(self, batch: InterviewBatch) -> None:
        row = await self._s.get(m.InterviewBatchModel, batch.id)
        if row is None:
            return
        row.role_title = batch.role_title
        row.window_opens_at = batch.window_opens_at
        row.window_closes_at = batch.window_closes_at
        row.status = batch.status
        row.total_count = batch.total_count
        row.sent_count = batch.sent_count
        row.failed_count = batch.failed_count
        row.updated_at = datetime.now(UTC)

    async def list_for_tenant(self, tenant_id: TenantId) -> list[InterviewBatch]:
        rows = (
            await self._s.execute(
                select(m.InterviewBatchModel)
                .where(m.InterviewBatchModel.tenant_id == tenant_id)
                .order_by(m.InterviewBatchModel.created_at.desc())
            )
        ).scalars().all()
        return [map_.interview_batch_to_domain(r) for r in rows]

    async def increment_counts(
        self, tenant_id: TenantId, batch_id: InterviewBatchId, *, total: int = 0, sent: int = 0, failed: int = 0
    ) -> None:
        await self._s.execute(
            update(m.InterviewBatchModel)
            .where(
                m.InterviewBatchModel.id == batch_id,
                m.InterviewBatchModel.tenant_id == tenant_id,
            )
            .values(
                total_count=m.InterviewBatchModel.total_count + total,
                sent_count=m.InterviewBatchModel.sent_count + sent,
                failed_count=m.InterviewBatchModel.failed_count + failed,
                updated_at=datetime.now(UTC),
            )
        )


class BatchCandidateRepositoryImpl:
    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    async def add(self, candidate: BatchCandidate) -> None:
        self._s.add(_batch_candidate_to_row(candidate))

    async def add_many(self, candidates: list[BatchCandidate]) -> None:
        for candidate in candidates:
            self._s.add(_batch_candidate_to_row(candidate))

    async def get(self, tenant_id: TenantId, candidate_id: BatchCandidateId) -> BatchCandidate | None:
        row = (
            await self._s.execute(
                select(m.BatchCandidateModel).where(
                    m.BatchCandidateModel.id == candidate_id,
                    m.BatchCandidateModel.tenant_id == tenant_id,
                )
            )
        ).scalar_one_or_none()
        return map_.batch_candidate_to_domain(row) if row else None

    async def update(self, candidate: BatchCandidate) -> None:
        row = await self._s.get(m.BatchCandidateModel, candidate.id)
        if row is None:
            return
        row.candidate_name = candidate.candidate_name
        row.candidate_email = candidate.candidate_email
        row.status = candidate.status
        row.error = candidate.error
        row.interview_id = candidate.interview_id
        row.updated_at = datetime.now(UTC)

    async def list_for_batch(
        self, tenant_id: TenantId, batch_id: InterviewBatchId
    ) -> list[BatchCandidate]:
        rows = (
            await self._s.execute(
                select(m.BatchCandidateModel)
                .where(
                    m.BatchCandidateModel.batch_id == batch_id,
                    m.BatchCandidateModel.tenant_id == tenant_id,
                )
                .order_by(m.BatchCandidateModel.created_at.asc())
            )
        ).scalars().all()
        return [map_.batch_candidate_to_domain(r) for r in rows]


def _batch_candidate_to_row(candidate: BatchCandidate) -> m.BatchCandidateModel:
    return m.BatchCandidateModel(
        id=candidate.id,
        tenant_id=candidate.tenant_id,
        batch_id=candidate.batch_id,
        resume_document_id=candidate.resume_document_id,
        resume_filename=candidate.resume_filename,
        candidate_name=candidate.candidate_name,
        candidate_email=candidate.candidate_email,
        status=candidate.status,
        error=candidate.error,
        interview_id=candidate.interview_id,
        created_at=candidate.created_at,
        updated_at=candidate.updated_at,
    )


class OAuthConnectionRepositoryImpl:
    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    async def get(self, tenant_id: TenantId, provider: str) -> OAuthConnection | None:
        row = await self._s.get(m.OAuthConnectionModel, (tenant_id, provider))
        return map_.oauth_connection_to_domain(row) if row else None

    async def list_for_tenant(self, tenant_id: TenantId) -> list[OAuthConnection]:
        rows = (
            await self._s.execute(
                select(m.OAuthConnectionModel).where(
                    m.OAuthConnectionModel.tenant_id == tenant_id
                )
            )
        ).scalars()
        return [map_.oauth_connection_to_domain(r) for r in rows]

    async def upsert(self, connection: OAuthConnection) -> None:
        row = await self._s.get(
            m.OAuthConnectionModel, (connection.tenant_id, connection.provider)
        )
        if row is None:
            self._s.add(
                m.OAuthConnectionModel(
                    tenant_id=connection.tenant_id,
                    provider=connection.provider,
                    access_token=connection.access_token,
                    refresh_token=connection.refresh_token,
                    expires_at=connection.expires_at,
                    scope=connection.scope,
                    account_label=connection.account_label,
                    created_at=connection.created_at,
                    updated_at=connection.updated_at,
                )
            )
            return
        row.access_token = connection.access_token
        # Re-consent does not always return a refresh token. Keeping the stored
        # one rather than blanking it is what stops a reconnect from silently
        # turning a long-lived connection into an hour-long one.
        if connection.refresh_token:
            row.refresh_token = connection.refresh_token
        row.expires_at = connection.expires_at
        row.scope = connection.scope
        if connection.account_label:
            row.account_label = connection.account_label
        row.updated_at = datetime.now(UTC)

    async def delete(self, tenant_id: TenantId, provider: str) -> None:
        row = await self._s.get(m.OAuthConnectionModel, (tenant_id, provider))
        if row is not None:
            await self._s.delete(row)


class GoogleConnectionRepositoryImpl:
    """Interview scheduling's narrower view of `oauth_connections`.

    Calendar code only ever means one provider, so it gets an interface that
    doesn't make it say so on every call. Same rows, same table.
    """

    PROVIDER = "google_calendar"

    def __init__(self, session: AsyncSession) -> None:
        self._s = session
        self._generic = OAuthConnectionRepositoryImpl(session)

    async def get(self, tenant_id: TenantId) -> GoogleOAuthConnection | None:
        row = await self._s.get(m.OAuthConnectionModel, (tenant_id, self.PROVIDER))
        return map_.google_connection_to_domain(row) if row else None

    async def upsert(self, connection: GoogleOAuthConnection) -> None:
        await self._generic.upsert(
            OAuthConnection(
                tenant_id=connection.tenant_id,
                provider=self.PROVIDER,
                access_token=connection.access_token,
                refresh_token=connection.refresh_token,
                expires_at=connection.expires_at,
                scope=connection.scope,
                account_label=connection.connected_email,
                created_at=connection.created_at,
                updated_at=connection.updated_at,
            )
        )

    async def delete(self, tenant_id: TenantId) -> None:
        await self._generic.delete(tenant_id, self.PROVIDER)


class WhatsAppChannelRepositoryImpl:
    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    async def add(self, channel: WhatsAppChannel) -> None:
        self._s.add(
            m.WhatsAppChannelModel(
                id=channel.id,
                tenant_id=channel.tenant_id,
                chatbot_id=channel.chatbot_id,
                phone_number=channel.phone_number,
                twilio_account_sid=channel.twilio_account_sid,
                twilio_auth_token=channel.twilio_auth_token,
                status=channel.status,
                created_at=channel.created_at,
                updated_at=channel.updated_at,
            )
        )

    async def get(self, tenant_id: TenantId, channel_id: uuid.UUID) -> WhatsAppChannel | None:
        row = (
            await self._s.execute(
                select(m.WhatsAppChannelModel).where(
                    m.WhatsAppChannelModel.id == channel_id,
                    m.WhatsAppChannelModel.tenant_id == tenant_id,
                )
            )
        ).scalar_one_or_none()
        return map_.whatsapp_channel_to_domain(row) if row else None

    async def get_by_chatbot(
        self, tenant_id: TenantId, chatbot_id: ChatbotId
    ) -> WhatsAppChannel | None:
        row = (
            await self._s.execute(
                select(m.WhatsAppChannelModel).where(
                    m.WhatsAppChannelModel.chatbot_id == chatbot_id,
                    m.WhatsAppChannelModel.tenant_id == tenant_id,
                )
            )
        ).scalar_one_or_none()
        return map_.whatsapp_channel_to_domain(row) if row else None

    async def get_by_phone_number(self, phone_number: str) -> WhatsAppChannel | None:
        row = (
            await self._s.execute(
                select(m.WhatsAppChannelModel).where(
                    m.WhatsAppChannelModel.phone_number == phone_number
                )
            )
        ).scalar_one_or_none()
        return map_.whatsapp_channel_to_domain(row) if row else None

    async def list_for_tenant(self, tenant_id: TenantId) -> list[WhatsAppChannel]:
        rows = (
            await self._s.execute(
                select(m.WhatsAppChannelModel).where(m.WhatsAppChannelModel.tenant_id == tenant_id)
            )
        ).scalars()
        return [map_.whatsapp_channel_to_domain(r) for r in rows]

    async def delete(self, tenant_id: TenantId, channel_id: uuid.UUID) -> None:
        row = (
            await self._s.execute(
                select(m.WhatsAppChannelModel).where(
                    m.WhatsAppChannelModel.id == channel_id,
                    m.WhatsAppChannelModel.tenant_id == tenant_id,
                )
            )
        ).scalar_one_or_none()
        if row is not None:
            await self._s.delete(row)


class WhatsAppConversationRepositoryImpl:
    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    async def get(
        self, whatsapp_channel_id: uuid.UUID, phone_number: str
    ) -> WhatsAppConversation | None:
        row = (
            await self._s.execute(
                select(m.WhatsAppConversationModel).where(
                    m.WhatsAppConversationModel.whatsapp_channel_id == whatsapp_channel_id,
                    m.WhatsAppConversationModel.phone_number == phone_number,
                )
            )
        ).scalar_one_or_none()
        return map_.whatsapp_conversation_to_domain(row) if row else None

    async def add(self, conversation: WhatsAppConversation) -> None:
        self._s.add(
            m.WhatsAppConversationModel(
                id=conversation.id,
                whatsapp_channel_id=conversation.whatsapp_channel_id,
                phone_number=conversation.phone_number,
                session_id=conversation.session_id,
                auto_reply=conversation.auto_reply,
                created_at=conversation.created_at,
                updated_at=conversation.updated_at,
            )
        )


class PostCallConfigRepositoryImpl:
    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    async def add(self, config: PostCallConfig) -> None:
        self._s.add(_post_call_config_to_row(config))

    async def get(self, tenant_id: TenantId, config_id: uuid.UUID) -> PostCallConfig | None:
        row = (
            await self._s.execute(
                select(m.PostCallConfigModel).where(
                    m.PostCallConfigModel.id == config_id,
                    m.PostCallConfigModel.tenant_id == tenant_id,
                )
            )
        ).scalar_one_or_none()
        return map_.post_call_config_to_domain(row) if row else None

    async def list_for_chatbot(
        self, tenant_id: TenantId, chatbot_id: ChatbotId
    ) -> list[PostCallConfig]:
        rows = (
            await self._s.execute(
                select(m.PostCallConfigModel)
                .where(
                    m.PostCallConfigModel.tenant_id == tenant_id,
                    m.PostCallConfigModel.chatbot_id == chatbot_id,
                )
                .order_by(m.PostCallConfigModel.created_at)
            )
        ).scalars()
        return [map_.post_call_config_to_domain(r) for r in rows]

    async def update(self, config: PostCallConfig) -> None:
        row = await self._s.get(m.PostCallConfigModel, config.id)
        if row is None:
            return
        row.delivery_method = config.delivery_method
        row.webhook_url = config.webhook_url
        row.email_to = config.email_to
        row.trigger_statuses = list(config.trigger_statuses)
        row.include_summary = config.include_summary
        row.include_transcript = config.include_transcript
        row.include_sentiment = config.include_sentiment
        row.include_extracted = config.include_extracted
        row.enabled = config.enabled

    async def delete(self, tenant_id: TenantId, config_id: uuid.UUID) -> None:
        row = (
            await self._s.execute(
                select(m.PostCallConfigModel).where(
                    m.PostCallConfigModel.id == config_id,
                    m.PostCallConfigModel.tenant_id == tenant_id,
                )
            )
        ).scalar_one_or_none()
        if row is not None:
            await self._s.delete(row)


def _post_call_config_to_row(c: PostCallConfig) -> m.PostCallConfigModel:
    return m.PostCallConfigModel(
        id=c.id,
        tenant_id=c.tenant_id,
        chatbot_id=c.chatbot_id,
        delivery_method=c.delivery_method,
        webhook_url=c.webhook_url,
        email_to=c.email_to,
        trigger_statuses=list(c.trigger_statuses),
        include_summary=c.include_summary,
        include_transcript=c.include_transcript,
        include_sentiment=c.include_sentiment,
        include_extracted=c.include_extracted,
        enabled=c.enabled,
        created_at=c.created_at,
    )


class PostCallDeliveryRepositoryImpl:
    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    async def claim(self, delivery: PostCallDelivery) -> bool:
        """Insert the delivery row, returning False when this (config, session)
        pair was already dispatched.

        This is the idempotency gate, enforced by the unique constraint rather
        than a read-then-write check — two concurrent "session ended" calls
        would both pass a read check and double-post to the customer's ATS.
        """
        stmt = (
            pg_insert(m.PostCallDeliveryModel)
            .values(
                id=delivery.id,
                tenant_id=delivery.tenant_id,
                chatbot_id=delivery.chatbot_id,
                config_id=delivery.config_id,
                session_id=delivery.session_id,
                call_status=delivery.call_status,
                delivery_method=delivery.delivery_method,
                destination=delivery.destination,
                status=delivery.status,
                error=delivery.error,
                payload=delivery.payload,
                created_at=delivery.created_at,
            )
            .on_conflict_do_nothing(constraint="uq_post_call_delivery_config_session")
            .returning(m.PostCallDeliveryModel.id)
        )
        return (await self._s.execute(stmt)).scalar_one_or_none() is not None

    async def finish(self, delivery: PostCallDelivery) -> None:
        row = await self._s.get(m.PostCallDeliveryModel, delivery.id)
        if row is None:
            return
        row.status = delivery.status
        row.error = delivery.error
        row.payload = delivery.payload

    async def list_for_chatbot(
        self, tenant_id: TenantId, chatbot_id: ChatbotId, limit: int = 50
    ) -> list[PostCallDelivery]:
        rows = (
            await self._s.execute(
                select(m.PostCallDeliveryModel)
                .where(
                    m.PostCallDeliveryModel.tenant_id == tenant_id,
                    m.PostCallDeliveryModel.chatbot_id == chatbot_id,
                )
                .order_by(m.PostCallDeliveryModel.created_at.desc())
                .limit(limit)
            )
        ).scalars()
        return [map_.post_call_delivery_to_domain(r) for r in rows]


class BroadcastRepositoryImpl:
    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    async def add(self, broadcast: Broadcast) -> None:
        self._s.add(
            m.BroadcastModel(
                id=broadcast.id,
                tenant_id=broadcast.tenant_id,
                chatbot_id=broadcast.chatbot_id,
                whatsapp_channel_id=broadcast.whatsapp_channel_id,
                whatsapp_session_id=broadcast.whatsapp_session_id,
                sender_kind=broadcast.sender_kind,
                mode=broadcast.mode,
                name=broadcast.name,
                message_template=broadcast.message_template,
                status=broadcast.status,
                total_count=broadcast.total_count,
                sent_count=broadcast.sent_count,
                delivered_count=broadcast.delivered_count,
                read_count=broadcast.read_count,
                replied_count=broadcast.replied_count,
                failed_count=broadcast.failed_count,
                created_at=broadcast.created_at,
                updated_at=broadcast.updated_at,
            )
        )

    async def get(self, tenant_id: TenantId, broadcast_id: uuid.UUID) -> Broadcast | None:
        row = (
            await self._s.execute(
                select(m.BroadcastModel).where(
                    m.BroadcastModel.id == broadcast_id,
                    m.BroadcastModel.tenant_id == tenant_id,
                )
            )
        ).scalar_one_or_none()
        return map_.broadcast_to_domain(row) if row else None

    async def get_unscoped(self, broadcast_id: uuid.UUID) -> Broadcast | None:
        """Resolve without a tenant filter — used only by the Twilio status
        callback, which carries no tenant context (mirrors
        WhatsAppChannelRepository.get_by_phone_number)."""
        row = await self._s.get(m.BroadcastModel, broadcast_id)
        return map_.broadcast_to_domain(row) if row else None

    async def list_for_tenant(self, tenant_id: TenantId) -> list[Broadcast]:
        rows = (
            await self._s.execute(
                select(m.BroadcastModel)
                .where(m.BroadcastModel.tenant_id == tenant_id)
                .order_by(m.BroadcastModel.created_at.desc())
            )
        ).scalars()
        return [map_.broadcast_to_domain(r) for r in rows]

    async def list_active(self) -> list[Broadcast]:
        """Campaigns the send sweep should work on. Deliberately not
        tenant-scoped: the sweep runs as a background job across all tenants."""
        rows = (
            await self._s.execute(
                select(m.BroadcastModel).where(m.BroadcastModel.status == "sending")
            )
        ).scalars()
        return [map_.broadcast_to_domain(r) for r in rows]

    async def update(self, broadcast: Broadcast) -> None:
        row = await self._s.get(m.BroadcastModel, broadcast.id)
        if row is None:
            return
        row.name = broadcast.name
        row.message_template = broadcast.message_template
        row.status = broadcast.status
        row.total_count = broadcast.total_count
        row.sent_count = broadcast.sent_count
        row.delivered_count = broadcast.delivered_count
        row.read_count = broadcast.read_count
        row.replied_count = broadcast.replied_count
        row.failed_count = broadcast.failed_count
        row.updated_at = broadcast.updated_at

    async def delete(self, tenant_id: TenantId, broadcast_id: uuid.UUID) -> None:
        row = (
            await self._s.execute(
                select(m.BroadcastModel).where(
                    m.BroadcastModel.id == broadcast_id,
                    m.BroadcastModel.tenant_id == tenant_id,
                )
            )
        ).scalar_one_or_none()
        if row is not None:
            await self._s.delete(row)


class BroadcastRecipientRepositoryImpl:
    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    async def add_many(self, recipients: list[BroadcastRecipient]) -> int:
        """Bulk-insert, skipping numbers already on this campaign. Returns how
        many rows were created so the UI can report the duplicate count."""
        if not recipients:
            return 0
        stmt = (
            pg_insert(m.BroadcastRecipientModel)
            .values(
                [
                    {
                        "id": r.id,
                        "broadcast_id": r.broadcast_id,
                        "tenant_id": r.tenant_id,
                        "phone_number": r.phone_number,
                        "display_name": r.display_name,
                        "status": r.status,
                        "error": r.error,
                        "provider_message_id": r.provider_message_id,
                        "session_id": r.session_id,
                        "attempts": r.attempts,
                        "created_at": r.created_at,
                        "updated_at": r.updated_at,
                    }
                    for r in recipients
                ]
            )
            .on_conflict_do_nothing(constraint="uq_broadcast_recipient_phone")
            .returning(m.BroadcastRecipientModel.id)
        )
        return len((await self._s.execute(stmt)).scalars().all())

    async def get(
        self, tenant_id: TenantId, recipient_id: uuid.UUID
    ) -> BroadcastRecipient | None:
        row = (
            await self._s.execute(
                select(m.BroadcastRecipientModel).where(
                    m.BroadcastRecipientModel.id == recipient_id,
                    m.BroadcastRecipientModel.tenant_id == tenant_id,
                )
            )
        ).scalar_one_or_none()
        return map_.broadcast_recipient_to_domain(row) if row else None

    async def get_by_provider_message_id(
        self, provider_message_id: str
    ) -> BroadcastRecipient | None:
        """Twilio status callbacks identify the recipient only by message SID
        and carry no tenant context — so this lookup is deliberately unscoped."""
        if not provider_message_id:
            return None
        row = (
            await self._s.execute(
                select(m.BroadcastRecipientModel).where(
                    m.BroadcastRecipientModel.provider_message_id == provider_message_id
                )
            )
        ).scalar_one_or_none()
        return map_.broadcast_recipient_to_domain(row) if row else None

    async def get_by_session(self, session_id: SessionId) -> BroadcastRecipient | None:
        """Used by the inbound webhook to flip a recipient to `replied` — the
        webhook knows the session it appended to, not the campaign."""
        row = (
            (
                await self._s.execute(
                    select(m.BroadcastRecipientModel).where(
                        m.BroadcastRecipientModel.session_id == session_id
                    )
                )
            )
            .scalars()
            .first()
        )
        return map_.broadcast_recipient_to_domain(row) if row else None

    async def list_for_broadcast(
        self,
        broadcast_id: uuid.UUID,
        *,
        status: str | None = None,
        search: str | None = None,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[BroadcastRecipient]:
        stmt = select(m.BroadcastRecipientModel).where(
            m.BroadcastRecipientModel.broadcast_id == broadcast_id
        )
        stmt = _recipient_filters(stmt, status, search)
        stmt = stmt.order_by(m.BroadcastRecipientModel.created_at)
        if limit is not None:
            stmt = stmt.limit(limit).offset(offset)
        rows = (await self._s.execute(stmt)).scalars()
        return [map_.broadcast_recipient_to_domain(r) for r in rows]

    async def count_for_broadcast(
        self, broadcast_id: uuid.UUID, *, status: str | None = None, search: str | None = None
    ) -> int:
        stmt = (
            select(func.count())
            .select_from(m.BroadcastRecipientModel)
            .where(m.BroadcastRecipientModel.broadcast_id == broadcast_id)
        )
        stmt = _recipient_filters(stmt, status, search)
        return int((await self._s.execute(stmt)).scalar_one())

    async def claim_pending(
        self, broadcast_id: uuid.UUID, limit: int
    ) -> list[BroadcastRecipient]:
        """Take the next batch of unsent recipients, locking them for this worker.

        SKIP LOCKED is what lets the sweep run on more than one process (or be
        re-entered by a retried background task) without two workers messaging
        the same person twice.
        """
        rows = (
            await self._s.execute(
                select(m.BroadcastRecipientModel)
                .where(
                    m.BroadcastRecipientModel.broadcast_id == broadcast_id,
                    m.BroadcastRecipientModel.status == "pending",
                )
                .order_by(m.BroadcastRecipientModel.created_at)
                .limit(limit)
                .with_for_update(skip_locked=True)
            )
        ).scalars()
        return [map_.broadcast_recipient_to_domain(r) for r in rows]

    async def update(self, recipient: BroadcastRecipient) -> None:
        row = await self._s.get(m.BroadcastRecipientModel, recipient.id)
        if row is None:
            return
        row.display_name = recipient.display_name
        row.status = recipient.status
        row.error = recipient.error
        row.provider_message_id = recipient.provider_message_id
        row.session_id = recipient.session_id
        row.attempts = recipient.attempts
        row.updated_at = recipient.updated_at

    async def reset_failed(self, broadcast_id: uuid.UUID) -> int:
        """Requeue every failed recipient; returns how many were requeued."""
        result = await self._s.execute(
            update(m.BroadcastRecipientModel)
            .where(
                m.BroadcastRecipientModel.broadcast_id == broadcast_id,
                m.BroadcastRecipientModel.status == "failed",
            )
            .values(
                status="pending",
                error="",
                provider_message_id="",
                updated_at=datetime.now(UTC),
            )
        )
        return int(result.rowcount or 0)


def _recipient_filters(stmt, status: str | None, search: str | None):
    """Shared WHERE clauses for the list/count pair, so a filtered page and its
    total can never disagree about what they're filtering on."""
    if status:
        stmt = stmt.where(m.BroadcastRecipientModel.status == status)
    if search and search.strip():
        like = f"%{search.strip()}%"
        stmt = stmt.where(
            m.BroadcastRecipientModel.phone_number.ilike(like)
            | m.BroadcastRecipientModel.display_name.ilike(like)
        )
    return stmt


class TenantIntegrationRepositoryImpl:
    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    async def upsert(self, integration: TenantIntegration) -> None:
        """Connect or re-connect in one statement.

        Re-connecting is how a tenant rotates a leaked webhook URL, so this
        overwrites config rather than erroring on the (tenant, integration)
        unique constraint.
        """
        stmt = (
            pg_insert(m.TenantIntegrationModel)
            .values(
                id=integration.id,
                tenant_id=integration.tenant_id,
                integration_id=integration.integration_id,
                config=integration.config,
                enabled=integration.enabled,
                created_at=integration.created_at,
                updated_at=integration.updated_at,
            )
            .on_conflict_do_update(
                constraint="uq_tenant_integration",
                set_={
                    "config": integration.config,
                    "enabled": integration.enabled,
                    "updated_at": integration.updated_at,
                },
            )
        )
        await self._s.execute(stmt)

    async def get(self, tenant_id: TenantId, integration_id: str) -> TenantIntegration | None:
        row = (
            await self._s.execute(
                select(m.TenantIntegrationModel).where(
                    m.TenantIntegrationModel.tenant_id == tenant_id,
                    m.TenantIntegrationModel.integration_id == integration_id,
                )
            )
        ).scalar_one_or_none()
        return map_.tenant_integration_to_domain(row) if row else None

    async def list_for_tenant(self, tenant_id: TenantId) -> list[TenantIntegration]:
        rows = (
            await self._s.execute(
                select(m.TenantIntegrationModel)
                .where(m.TenantIntegrationModel.tenant_id == tenant_id)
                .order_by(m.TenantIntegrationModel.created_at)
            )
        ).scalars()
        return [map_.tenant_integration_to_domain(r) for r in rows]

    async def delete(self, tenant_id: TenantId, integration_id: str) -> None:
        await self._s.execute(
            delete(m.TenantIntegrationModel).where(
                m.TenantIntegrationModel.tenant_id == tenant_id,
                m.TenantIntegrationModel.integration_id == integration_id,
            )
        )


class IssueReportRepositoryImpl:
    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    async def add(self, report: IssueReport) -> None:
        self._s.add(
            m.IssueReportModel(
                id=report.id,
                tenant_id=report.tenant_id,
                name=report.name,
                email=report.email,
                phone=report.phone,
                report_type=report.report_type,
                priority=report.priority,
                subject=report.subject,
                description=report.description,
                status=report.status,
                page_url=report.page_url,
                user_agent=report.user_agent,
                email_sent=report.email_sent,
                created_at=report.created_at,
            )
        )

    async def get(self, tenant_id: TenantId, report_id: uuid.UUID) -> IssueReport | None:
        row = (
            await self._s.execute(
                select(m.IssueReportModel).where(
                    m.IssueReportModel.id == report_id,
                    m.IssueReportModel.tenant_id == tenant_id,
                )
            )
        ).scalar_one_or_none()
        return map_.issue_report_to_domain(row) if row else None

    async def list_for_tenant(self, tenant_id: TenantId, limit: int = 100) -> list[IssueReport]:
        rows = (
            await self._s.execute(
                select(m.IssueReportModel)
                .where(m.IssueReportModel.tenant_id == tenant_id)
                .order_by(m.IssueReportModel.created_at.desc())
                .limit(limit)
            )
        ).scalars()
        return [map_.issue_report_to_domain(r) for r in rows]

    async def mark_email_sent(self, report_id: uuid.UUID, sent: bool) -> None:
        row = await self._s.get(m.IssueReportModel, report_id)
        if row is not None:
            row.email_sent = sent


class VoiceProfileRepositoryImpl:
    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    async def add(self, profile: VoiceProfile) -> None:
        self._s.add(
            m.VoiceProfileModel(
                id=profile.id,
                tenant_id=profile.tenant_id,
                name=profile.name,
                gender=profile.gender,
                language=profile.language,
                description=profile.description,
                sample_storage_key=profile.sample_storage_key,
                sample_content_type=profile.sample_content_type,
                sample_bytes=profile.sample_bytes,
                duration_seconds=profile.duration_seconds,
                provider=profile.provider,
                provider_voice_id=profile.provider_voice_id,
                status=profile.status,
                error=profile.error,
                created_at=profile.created_at,
                updated_at=profile.updated_at,
            )
        )

    async def get(self, tenant_id: TenantId, profile_id: uuid.UUID) -> VoiceProfile | None:
        row = (
            await self._s.execute(
                select(m.VoiceProfileModel).where(
                    m.VoiceProfileModel.id == profile_id,
                    m.VoiceProfileModel.tenant_id == tenant_id,
                )
            )
        ).scalar_one_or_none()
        return map_.voice_profile_to_domain(row) if row else None

    async def list_for_tenant(self, tenant_id: TenantId) -> list[VoiceProfile]:
        rows = (
            await self._s.execute(
                select(m.VoiceProfileModel)
                .where(m.VoiceProfileModel.tenant_id == tenant_id)
                .order_by(m.VoiceProfileModel.created_at.desc())
            )
        ).scalars()
        return [map_.voice_profile_to_domain(r) for r in rows]

    async def update(self, profile: VoiceProfile) -> None:
        row = await self._s.get(m.VoiceProfileModel, profile.id)
        if row is None:
            return
        row.name = profile.name
        row.gender = profile.gender
        row.language = profile.language
        row.description = profile.description
        row.provider = profile.provider
        row.provider_voice_id = profile.provider_voice_id
        row.status = profile.status
        row.error = profile.error
        row.updated_at = profile.updated_at

    async def delete(self, tenant_id: TenantId, profile_id: uuid.UUID) -> None:
        await self._s.execute(
            delete(m.VoiceProfileModel).where(
                m.VoiceProfileModel.id == profile_id,
                m.VoiceProfileModel.tenant_id == tenant_id,
            )
        )


class WhatsAppWebSessionRepositoryImpl:
    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    async def add(self, ws: WhatsAppWebSession) -> None:
        self._s.add(
            m.WhatsAppWebSessionModel(
                id=ws.id,
                tenant_id=ws.tenant_id,
                chatbot_id=ws.chatbot_id,
                status=ws.status,
                phone_number=ws.phone_number,
                display_name=ws.display_name,
                qr_data_url=ws.qr_data_url,
                qr_expires_at=ws.qr_expires_at,
                last_error=ws.last_error,
                linked_at=ws.linked_at,
                last_seen_at=ws.last_seen_at,
                created_at=ws.created_at,
                updated_at=ws.updated_at,
            )
        )

    async def get(self, tenant_id: TenantId, session_id: uuid.UUID) -> WhatsAppWebSession | None:
        row = (
            await self._s.execute(
                select(m.WhatsAppWebSessionModel).where(
                    m.WhatsAppWebSessionModel.id == session_id,
                    m.WhatsAppWebSessionModel.tenant_id == tenant_id,
                )
            )
        ).scalar_one_or_none()
        return map_.whatsapp_web_session_to_domain(row) if row else None

    async def get_unscoped(self, session_id: uuid.UUID) -> WhatsAppWebSession | None:
        """Resolve without a tenant filter — only the bridge webhook uses this,
        and it carries no tenant context (mirrors the Twilio callbacks)."""
        row = await self._s.get(m.WhatsAppWebSessionModel, session_id)
        return map_.whatsapp_web_session_to_domain(row) if row else None

    async def list_for_tenant(self, tenant_id: TenantId) -> list[WhatsAppWebSession]:
        rows = (
            await self._s.execute(
                select(m.WhatsAppWebSessionModel)
                .where(m.WhatsAppWebSessionModel.tenant_id == tenant_id)
                .order_by(m.WhatsAppWebSessionModel.created_at.desc())
            )
        ).scalars()
        return [map_.whatsapp_web_session_to_domain(r) for r in rows]

    async def update(self, ws: WhatsAppWebSession) -> None:
        row = await self._s.get(m.WhatsAppWebSessionModel, ws.id)
        if row is None:
            return
        row.chatbot_id = ws.chatbot_id
        row.status = ws.status
        row.phone_number = ws.phone_number
        row.display_name = ws.display_name
        row.qr_data_url = ws.qr_data_url
        row.qr_expires_at = ws.qr_expires_at
        row.last_error = ws.last_error
        row.linked_at = ws.linked_at
        row.last_seen_at = ws.last_seen_at
        row.updated_at = ws.updated_at

    async def delete(self, tenant_id: TenantId, session_id: uuid.UUID) -> None:
        await self._s.execute(
            delete(m.WhatsAppWebSessionModel).where(
                m.WhatsAppWebSessionModel.id == session_id,
                m.WhatsAppWebSessionModel.tenant_id == tenant_id,
            )
        )
