"""HTTP request/response models (the public API contract).

Kept separate from application DTOs so the wire format can evolve independently
of internal use-case signatures.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, EmailStr, Field

# Verdict vocabulary shared with hiring_agent's collect_feedback_tool.
InterviewVerdict = Literal["strong_hire", "hire", "maybe", "no_hire"]
InterviewStatus = Literal["scheduled", "in_progress", "completed", "cancelled"]


# --- Auth ---
class RegisterRequest(BaseModel):
    tenant_name: str = Field(min_length=2, max_length=120)
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    tenant_id: uuid.UUID
    user_id: uuid.UUID
    role: str


# --- Team (per-tenant admin panel: roles + teammate invites) ---
TeamRole = Literal["admin", "member", "viewer"]


class InviteTeammateRequest(BaseModel):
    email: EmailStr
    role: TeamRole = "member"


class TenantInviteResponse(BaseModel):
    id: uuid.UUID
    email: str
    role: str
    status: str
    expires_at: datetime
    invite_url: str
    email_sent: bool = False


class TeamMemberResponse(BaseModel):
    id: uuid.UUID
    email: str
    role: str
    is_active: bool
    created_at: datetime


class TeamResponse(BaseModel):
    members: list[TeamMemberResponse]
    pending_invites: list[TenantInviteResponse]


class InviteBootstrapResponse(BaseModel):
    tenant_name: str
    email: str
    role: str
    valid: bool


class AcceptInviteRequest(BaseModel):
    password: str = Field(min_length=8, max_length=128)


# --- Documents ---
class CreateUploadRequest(BaseModel):
    filename: str
    content_type: str = "application/octet-stream"
    size_bytes: int = Field(gt=0)


class CreateTextDocumentRequest(BaseModel):
    filename: str = Field(default="", max_length=255)
    text: str = Field(min_length=1, max_length=2_000_000)


class CreateUploadResponse(BaseModel):
    document_id: uuid.UUID
    upload_url: str
    storage_key: str


class DocumentResponse(BaseModel):
    id: uuid.UUID
    filename: str
    status: str
    chunk_count: int
    error: str | None = None


# --- Chatbots ---
class WidgetConfigSchema(BaseModel):
    theme_color: str = Field(default="#4f46e5", max_length=32)
    display_name: str = Field(default="Assistant", min_length=1, max_length=60)
    welcome_message: str = Field(
        default="Hi! 👋 I'm here to help with our open roles — ask me about the positions or start your application.",
        max_length=300,
    )
    launcher_position: Literal["bottom-right", "bottom-left"] = "bottom-right"


class CreateChatbotRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    channel: Literal["text", "voice"] = "text"
    system_prompt: str | None = None
    top_k: int = Field(default=5, ge=1, le=20)
    is_public: bool = False
    allowed_document_ids: list[uuid.UUID] = Field(default_factory=list)


class UpdateChatbotRequest(BaseModel):
    """Partial update — only provided fields change. Used by the builder UI to
    edit appearance, sharing, and the embed allowlist."""

    name: str | None = Field(default=None, min_length=1, max_length=120)
    channel: Literal["text", "voice"] | None = None
    system_prompt: str | None = Field(default=None, min_length=1)
    top_k: int | None = Field(default=None, ge=1, le=20)
    is_public: bool | None = None
    allowed_origins: list[str] | None = Field(default=None, max_length=50)
    widget: WidgetConfigSchema | None = None


class ChatbotResponse(BaseModel):
    id: uuid.UUID
    name: str
    channel: Literal["text", "voice"]
    system_prompt: str
    top_k: int
    is_public: bool
    public_key: str
    allowed_origins: list[str]
    widget: WidgetConfigSchema
    # Convenience fields the builder UI copies/embeds directly.
    public_url: str
    embed_snippet: str


# --- Public widget (no auth; called from third-party pages) ---
class PublicConfigResponse(BaseModel):
    """Bootstrap payload the widget fetches to render itself. Deliberately leaks
    nothing sensitive — just appearance + the bot's display identity."""

    chatbot_id: uuid.UUID
    name: str
    channel: Literal["text", "voice"]
    widget: WidgetConfigSchema


class PublicCitation(BaseModel):
    ordinal: int
    score: float
    snippet: str


class PublicAnswerResponse(BaseModel):
    answer: str
    citations: list[PublicCitation]


# --- Chat ---
class CreateSessionResponse(BaseModel):
    session_id: uuid.UUID


class AskRequest(BaseModel):
    message: str = Field(min_length=1, max_length=8000)


class CitationResponse(BaseModel):
    document_id: uuid.UUID
    ordinal: int
    score: float
    snippet: str


class AnswerResponse(BaseModel):
    message_id: uuid.UUID
    answer: str
    citations: list[CitationResponse]
    tokens_used: int
    provider: str


# --- Agent ---
class AgentStepResponse(BaseModel):
    index: int
    thought: str
    action: str
    observation: str
    model: str


class AgentAnswerResponse(BaseModel):
    answer: str
    citations: list[CitationResponse]
    tokens_used: int
    provider: str | None
    stop_reason: str  # "final" | "max_steps" | "error"
    tools_used: list[str]
    steps: list[AgentStepResponse]


# --- Analytics ---
class AnalyticsDay(BaseModel):
    day: date
    answers: int
    avg_top_score: float | None
    avg_citations: float
    no_context_rate: float
    refusal_rate: float
    avg_tokens: float


class AnalyticsProvider(BaseModel):
    provider: str | None
    answers: int
    avg_top_score: float | None
    avg_tokens: float


class ChatbotAnalyticsResponse(BaseModel):
    chatbot_id: uuid.UUID
    days: int
    daily: list[AnalyticsDay]
    providers: list[AnalyticsProvider]


class RequestLogResponse(BaseModel):
    id: uuid.UUID
    created_at: datetime
    query: str
    status: str
    num_retrieved: int
    max_score: float | None
    no_context: bool
    refused: bool
    provider: str | None
    model: str | None
    tokens_used: int
    latency_ms: int
    error: str | None
    answer: str | None


# --- Virtual Interview ---
class ScheduleInterviewRequest(BaseModel):
    candidate_name: str = Field(default="", max_length=200)
    candidate_email: EmailStr
    role_title: str = Field(default="", max_length=200)
    job_document_id: uuid.UUID
    resume_document_id: uuid.UUID
    scheduled_at: datetime
    custom_questions: list[str] = Field(default_factory=list)


class QuestionScoreResponse(BaseModel):
    question: str
    answer: str
    score: int
    justification: str


class TranscriptTurnResponse(BaseModel):
    role: Literal["assistant", "user"]
    content: str


class InterviewResponse(BaseModel):
    id: uuid.UUID
    candidate_name: str
    candidate_email: str
    role_title: str
    scheduled_at: datetime
    status: InterviewStatus
    questions: list[str]
    transcript: list[TranscriptTurnResponse]
    calendar_link: str | None
    overall_score: float | None
    overall_verdict: InterviewVerdict | None
    scores: list[QuestionScoreResponse]
    has_report: bool
    join_url: str
    calendar_created: bool = False
    email_sent: bool = False


# --- Virtual Interview: candidate-facing (token-scoped, no auth) ---
class InterviewBootstrapResponse(BaseModel):
    candidate_name: str
    role_title: str
    tenant_name: str
    scheduled_at: datetime
    status: InterviewStatus
    can_join: bool


# --- Bulk interview invites ---
BatchStatus = Literal["collecting", "sending", "completed"]
CandidateStatus = Literal["ingesting", "needs_review", "excluded", "scheduled", "failed"]


class CreateBatchRequest(BaseModel):
    role_title: str = Field(default="", max_length=200)
    job_document_id: uuid.UUID
    window_opens_at: datetime
    window_closes_at: datetime | None = None
    custom_questions: list[str] = Field(default_factory=list)


class AttachBatchResumeRequest(BaseModel):
    resume_document_id: uuid.UUID
    resume_filename: str = Field(default="", max_length=500)


class PatchBatchCandidateRequest(BaseModel):
    candidate_name: str | None = Field(default=None, max_length=200)
    candidate_email: str | None = Field(default=None, max_length=320)
    excluded: bool | None = None


class BatchCandidateResponse(BaseModel):
    id: uuid.UUID
    resume_filename: str
    candidate_name: str
    candidate_email: str
    status: CandidateStatus
    error: str | None
    interview_id: uuid.UUID | None


class InterviewBatchResponse(BaseModel):
    id: uuid.UUID
    role_title: str
    job_document_id: uuid.UUID
    window_opens_at: datetime
    window_closes_at: datetime | None
    custom_questions: list[str] = Field(default_factory=list)
    status: BatchStatus
    total_count: int
    sent_count: int
    failed_count: int
    candidates: list[BatchCandidateResponse] = Field(default_factory=list)


# --- Google Calendar integration ---
class GoogleStatusResponse(BaseModel):
    connected: bool
    email: str = ""


class GoogleConnectResponse(BaseModel):
    authorize_url: str


# --- WhatsApp channel (via Twilio) ---
class ConnectWhatsAppRequest(BaseModel):
    chatbot_id: uuid.UUID
    phone_number: str = Field(min_length=5, max_length=32)
    twilio_account_sid: str = Field(min_length=1, max_length=64)
    twilio_auth_token: str = Field(min_length=1, max_length=255)


class WhatsAppChannelResponse(BaseModel):
    id: uuid.UUID
    chatbot_id: uuid.UUID
    chatbot_name: str
    phone_number: str
    status: str
    webhook_url: str
    created_at: datetime
