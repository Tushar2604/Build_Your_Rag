"""Map between domain entities and ORM models.

Kept in one place so the translation rules are easy to audit. Domain stays free
of SQLAlchemy; ORM stays free of business logic.
"""

from __future__ import annotations

import uuid

from src.application.ports.repositories import (
    GoogleOAuthConnection,
    WhatsAppChannel,
    WhatsAppConversation,
)
from src.domain.chat.entities import ChatSession, Citation, Message, MessageRole
from src.domain.chatbot.entities import Chatbot, RetrievalConfig, WidgetConfig
from src.domain.document.entities import Document, IngestionStatus
from src.domain.interview.batch_entities import BatchCandidate, InterviewBatch
from src.domain.interview.entities import Interview, QuestionScore, TranscriptTurn
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
from src.domain.tenant.entities import ApiKey, Role, Tenant, User
from src.infrastructure.persistence import models as m


def tenant_to_domain(row: m.TenantModel) -> Tenant:
    return Tenant(
        id=TenantId(row.id),
        name=row.name,
        slug=row.slug,
        daily_token_quota=row.daily_token_quota,
        max_documents=row.max_documents,
        is_active=row.is_active,
        created_at=row.created_at,
    )


def user_to_domain(row: m.UserModel) -> User:
    return User(
        id=UserId(row.id),
        email=row.email,
        password_hash=row.password_hash,
        tenant_id=TenantId(row.tenant_id),
        role=Role(row.role),
        is_active=row.is_active,
        created_at=row.created_at,
    )


def apikey_to_domain(row: m.ApiKeyModel) -> ApiKey:
    return ApiKey(
        id=row.id,
        tenant_id=TenantId(row.tenant_id),
        name=row.name,
        key_hash=row.key_hash,
        prefix=row.prefix,
        is_active=row.is_active,
        created_at=row.created_at,
    )


def document_to_domain(row: m.DocumentModel) -> Document:
    return Document(
        id=DocumentId(row.id),
        tenant_id=TenantId(row.tenant_id),
        filename=row.filename,
        content_type=row.content_type,
        size_bytes=row.size_bytes,
        storage_key=row.storage_key,
        checksum=row.checksum,
        status=IngestionStatus(row.status),
        chunk_count=row.chunk_count,
        error=row.error,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def chatbot_to_domain(row: m.ChatbotModel) -> Chatbot:
    rc = row.retrieval or {}
    wc = row.widget_config or {}
    default_widget = WidgetConfig()
    return Chatbot(
        id=ChatbotId(row.id),
        tenant_id=TenantId(row.tenant_id),
        name=row.name,
        channel=row.channel or "text",  # type: ignore[arg-type]
        system_prompt=row.system_prompt,
        retrieval=RetrievalConfig(
            top_k=rc.get("top_k", 5),
            min_score=rc.get("min_score", 0.0),
            rerank=rc.get("rerank", False),
        ),
        allowed_document_ids=[DocumentId(uuid.UUID(d)) for d in (row.allowed_document_ids or [])],
        is_public=row.is_public,
        public_key=row.public_key,
        allowed_origins=list(row.allowed_origins or []),
        widget=WidgetConfig(
            theme_color=wc.get("theme_color", default_widget.theme_color),
            display_name=wc.get("display_name", default_widget.display_name),
            welcome_message=wc.get("welcome_message", default_widget.welcome_message),
            launcher_position=wc.get("launcher_position", default_widget.launcher_position),
        ),
        created_at=row.created_at,
    )


def chatbot_retrieval_to_jsonb(rc: RetrievalConfig) -> dict:
    return {"top_k": rc.top_k, "min_score": rc.min_score, "rerank": rc.rerank}


def widget_config_to_jsonb(wc: WidgetConfig) -> dict:
    return {
        "theme_color": wc.theme_color,
        "display_name": wc.display_name,
        "welcome_message": wc.welcome_message,
        "launcher_position": wc.launcher_position,
    }


def session_to_domain(row: m.ChatSessionModel) -> ChatSession:
    return ChatSession(
        id=SessionId(row.id),
        tenant_id=TenantId(row.tenant_id),
        chatbot_id=ChatbotId(row.chatbot_id),
        title=row.title,
        created_at=row.created_at,
    )


def message_to_domain(row: m.ChatMessageModel) -> Message:
    return Message(
        id=MessageId(row.id),
        session_id=SessionId(row.session_id),
        tenant_id=TenantId(row.tenant_id),
        role=MessageRole(row.role),
        content=row.content,
        citations=[
            Citation(
                document_id=DocumentId(uuid.UUID(c["document_id"])),
                chunk_id=c["chunk_id"],
                ordinal=c["ordinal"],
                score=c["score"],
                snippet=c["snippet"],
            )
            for c in (row.citations or [])
        ],
        tokens_used=row.tokens_used,
        provider=row.provider,
        created_at=row.created_at,
    )


def citations_to_jsonb(citations: list[Citation]) -> list[dict]:
    return [
        {
            "document_id": str(c.document_id),
            "chunk_id": c.chunk_id,
            "ordinal": c.ordinal,
            "score": c.score,
            "snippet": c.snippet,
        }
        for c in citations
    ]


def interview_to_domain(row: m.InterviewModel) -> Interview:
    return Interview(
        id=InterviewId(row.id),
        tenant_id=TenantId(row.tenant_id),
        candidate_name=row.candidate_name,
        candidate_email=row.candidate_email,
        role_title=row.role_title,
        job_document_id=DocumentId(row.job_document_id),
        resume_document_id=DocumentId(row.resume_document_id),
        scheduled_at=row.scheduled_at,
        window_closes_at=row.window_closes_at,
        status=row.status,  # type: ignore[arg-type]
        access_token=row.access_token,
        questions=list(row.questions or []),
        transcript=[TranscriptTurn(role=t["role"], content=t["content"]) for t in (row.transcript or [])],
        current_question_index=row.current_question_index,
        google_event_id=row.google_event_id,
        calendar_link=row.calendar_link,
        report_storage_key=row.report_storage_key,
        overall_score=row.overall_score,
        overall_verdict=row.overall_verdict,
        scores=[
            QuestionScore(
                question=s["question"],
                answer=s.get("answer", ""),
                score=s["score"],
                justification=s.get("justification", ""),
            )
            for s in (row.scores or [])
        ],
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def transcript_to_jsonb(transcript: list[TranscriptTurn]) -> list[dict]:
    return [{"role": t.role, "content": t.content} for t in transcript]


def scores_to_jsonb(scores: list[QuestionScore]) -> list[dict]:
    return [
        {"question": s.question, "answer": s.answer, "score": s.score, "justification": s.justification}
        for s in scores
    ]


def interview_batch_to_domain(row: m.InterviewBatchModel) -> InterviewBatch:
    return InterviewBatch(
        id=InterviewBatchId(row.id),
        tenant_id=TenantId(row.tenant_id),
        role_title=row.role_title,
        job_document_id=DocumentId(row.job_document_id),
        window_opens_at=row.window_opens_at,
        window_closes_at=row.window_closes_at,
        status=row.status,  # type: ignore[arg-type]
        total_count=row.total_count,
        sent_count=row.sent_count,
        failed_count=row.failed_count,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def batch_candidate_to_domain(row: m.BatchCandidateModel) -> BatchCandidate:
    return BatchCandidate(
        id=BatchCandidateId(row.id),
        tenant_id=TenantId(row.tenant_id),
        batch_id=InterviewBatchId(row.batch_id),
        resume_document_id=DocumentId(row.resume_document_id),
        resume_filename=row.resume_filename,
        candidate_name=row.candidate_name,
        candidate_email=row.candidate_email,
        status=row.status,  # type: ignore[arg-type]
        error=row.error,
        interview_id=InterviewId(row.interview_id) if row.interview_id else None,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def google_connection_to_domain(row: m.GoogleOAuthConnectionModel) -> GoogleOAuthConnection:
    return GoogleOAuthConnection(
        tenant_id=TenantId(row.tenant_id),
        access_token=row.access_token,
        refresh_token=row.refresh_token,
        expires_at=row.expires_at,
        scope=row.scope,
        connected_email=row.connected_email,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def whatsapp_channel_to_domain(row: m.WhatsAppChannelModel) -> WhatsAppChannel:
    return WhatsAppChannel(
        id=row.id,
        tenant_id=TenantId(row.tenant_id),
        chatbot_id=ChatbotId(row.chatbot_id),
        phone_number=row.phone_number,
        twilio_account_sid=row.twilio_account_sid,
        twilio_auth_token=row.twilio_auth_token,
        status=row.status,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def whatsapp_conversation_to_domain(row: m.WhatsAppConversationModel) -> WhatsAppConversation:
    return WhatsAppConversation(
        id=row.id,
        whatsapp_channel_id=row.whatsapp_channel_id,
        phone_number=row.phone_number,
        session_id=SessionId(row.session_id),
        created_at=row.created_at,
        updated_at=row.updated_at,
    )
