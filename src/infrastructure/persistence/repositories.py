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
    ProviderStat,
    RequestLog,
    WhatsAppChannel,
    WhatsAppConversation,
)
from src.domain.chat.entities import ChatSession, Message
from src.domain.chatbot.entities import Chatbot
from src.domain.document.entities import Chunk, Document, IngestionStatus
from src.domain.interview.batch_entities import BatchCandidate, InterviewBatch
from src.domain.interview.entities import Interview
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
        if document_ids:
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
        self._s.add(_chatbot_to_row(chatbot))

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
        row.retrieval = map_.chatbot_retrieval_to_jsonb(chatbot.retrieval)
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
        retrieval=map_.chatbot_retrieval_to_jsonb(chatbot.retrieval),
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


class GoogleConnectionRepositoryImpl:
    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    async def get(self, tenant_id: TenantId) -> GoogleOAuthConnection | None:
        row = await self._s.get(m.GoogleOAuthConnectionModel, tenant_id)
        return map_.google_connection_to_domain(row) if row else None

    async def upsert(self, connection: GoogleOAuthConnection) -> None:
        row = await self._s.get(m.GoogleOAuthConnectionModel, connection.tenant_id)
        if row is None:
            self._s.add(
                m.GoogleOAuthConnectionModel(
                    tenant_id=connection.tenant_id,
                    access_token=connection.access_token,
                    refresh_token=connection.refresh_token,
                    expires_at=connection.expires_at,
                    scope=connection.scope,
                    connected_email=connection.connected_email,
                    created_at=connection.created_at,
                    updated_at=connection.updated_at,
                )
            )
        else:
            row.access_token = connection.access_token
            row.refresh_token = connection.refresh_token
            row.expires_at = connection.expires_at
            row.scope = connection.scope
            row.connected_email = connection.connected_email
            row.updated_at = datetime.now(UTC)

    async def delete(self, tenant_id: TenantId) -> None:
        row = await self._s.get(m.GoogleOAuthConnectionModel, tenant_id)
        if row is not None:
            await self._s.delete(row)


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
                created_at=conversation.created_at,
                updated_at=conversation.updated_at,
            )
        )
