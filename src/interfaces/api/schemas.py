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


class AuthProvidersResponse(BaseModel):
    """Sign-in methods this deployment offers, beyond email + password."""

    google: bool = False


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


class FlowSectionSchema(BaseModel):
    """One block of the Conversational Flow. `id` is absent when the UI has just
    added a section — the server mints one so reorder/toggle can address it."""

    id: uuid.UUID | None = None
    title: str = Field(min_length=1, max_length=120)
    body: str = Field(default="", max_length=6000)
    enabled: bool = True


class AssistantConfigSchema(BaseModel):
    """Runtime settings on the Assistant Details tab — see domain AssistantConfig."""

    direction: Literal["outgoing", "incoming"] = "outgoing"
    languages: list[str] = Field(default_factory=lambda: ["English (India)"], max_length=10)
    tts_voice: str = Field(default="Cartesia - Riya", max_length=80)
    llm_model: str = Field(default="gpt-4.1-mini", max_length=80)
    stt_model: str = Field(default="Soniox", max_length=80)
    welcome_message: str = Field(default="", max_length=600)
    welcome_dynamic: bool = True
    welcome_interruptible: bool = False


class AssistantOptionsResponse(BaseModel):
    """The dropdown contents for the Assistant Settings row. Served from the
    domain lists so the UI can never offer a value the backend rejects."""

    languages: list[str]
    tts_voices: list[str]
    llm_models: list[str]
    stt_models: list[str]
    use_cases: list[dict[str, str]]


class GenerateAssistantRequest(BaseModel):
    """Free-text description typed into the create box."""

    description: str = Field(min_length=10, max_length=4000)
    # One of the use-case chips. Free-form rather than an enum so adding a chip
    # is a one-line change; unknown values are simply ignored as a hint.
    use_case: str | None = Field(default=None, max_length=40)
    channel: Literal["text", "voice"] = "voice"


class RegenerateFlowRequest(BaseModel):
    """"Ask AI" on an existing assistant — refine or rebuild its flow."""

    description: str = Field(min_length=10, max_length=4000)
    use_case: str | None = Field(default=None, max_length=40)


class OAuthStartResponse(BaseModel):
    """The vendor consent URL. Returned as JSON rather than a redirect — see
    the module docstring on routers/oauth.py."""

    authorize_url: str


class OAuthStatusResponse(BaseModel):
    provider: str
    connected: bool
    account_label: str = ""
    # False when the server has no OAuth app registered for this vendor, which
    # is a different problem from "you haven't connected yet".
    configured: bool = False


class ChatbotCardCounts(BaseModel):
    """Per-assistant counts the list cards show at a glance."""

    knowledge_files: int = 0
    post_call_actions: int = 0
    integrations: int = 0


class AssistantKnowledgeDocument(BaseModel):
    """One document in this assistant's own knowledge base."""

    id: uuid.UUID
    filename: str
    status: str
    chunk_count: int
    error: str | None = None


class AssistantKnowledgeResponse(BaseModel):
    """This assistant's knowledge base.

    Only its own documents — an assistant never sees, or retrieves from, files
    uploaded for a different one. `ready_count` is what actually answers
    questions; the rest are still ingesting or failed.
    """

    documents: list[AssistantKnowledgeDocument]
    total_count: int
    ready_count: int


class AttachAssistantKnowledgeRequest(BaseModel):
    """Documents just uploaded for this assistant. Additive — see the route."""

    document_ids: list[uuid.UUID] = Field(default_factory=list, max_length=500)


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
    # `system_prompt` and `flow_sections` are two views of the same thing and
    # are mutually exclusive — sending both is rejected rather than silently
    # letting one win, which would make the editor lose the owner's edits.
    system_prompt: str | None = Field(default=None, min_length=1)
    flow_sections: list[FlowSectionSchema] | None = Field(default=None, max_length=40)
    top_k: int | None = Field(default=None, ge=1, le=20)
    is_public: bool | None = None
    allowed_origins: list[str] | None = Field(default=None, max_length=50)
    widget: WidgetConfigSchema | None = None
    # Cloned voice for spoken replies. Explicit null clears it back to the
    # browser default, so `None` here means "unchanged" and requires the caller
    # to opt in via `voice_profile_id_set`.
    voice_profile_id: uuid.UUID | None = None
    voice_profile_id_set: bool = False
    # Whole-object replace — the settings row is saved as a unit, and a partial
    # merge of eight independent knobs would make "which value won" unanswerable.
    assistant: AssistantConfigSchema | None = None
    # Which documents this assistant may retrieve from. Empty list = every ready
    # document in the tenant (see Chatbot.document_filter).
    allowed_document_ids: list[uuid.UUID] | None = Field(default=None, max_length=500)


class ChatbotResponse(BaseModel):
    id: uuid.UUID
    # Short id for humans ("#236637"). Assigned by the database, so it is
    # absent only for an assistant that has not been persisted yet.
    display_id: int | None = None
    name: str
    channel: Literal["text", "voice"]
    system_prompt: str
    # Empty when this bot was authored as a raw prompt; the editor then offers
    # to convert it into the stock sections.
    flow_sections: list[FlowSectionSchema]
    voice_profile_id: uuid.UUID | None = None
    assistant: AssistantConfigSchema
    top_k: int
    is_public: bool
    public_key: str
    allowed_origins: list[str]
    allowed_document_ids: list[uuid.UUID]
    widget: WidgetConfigSchema
    # Convenience fields the builder UI copies/embeds directly.
    public_url: str
    embed_snippet: str
    # False when the flow came from `fallback_blueprint` rather than the model —
    # only ever set on a generate response, so the UI can label it a draft.
    ai_generated: bool = True
    # Populated on list/get so a card needs no follow-up requests.
    counts: ChatbotCardCounts = Field(default_factory=ChatbotCardCounts)


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


# --- Post-call delivery ---
CallStatusLiteral = Literal["completed", "voicemail", "no_answer", "busy", "failed"]
DeliveryMethodLiteral = Literal["webhook", "email"]


class PostCallConfigBody(BaseModel):
    """Create/update payload. `webhook_url` and `email_to` are both optional
    here and validated against `delivery_method` in the domain, so the error the
    UI shows is the same one the domain enforces."""

    delivery_method: DeliveryMethodLiteral = "webhook"
    webhook_url: str = Field(default="", max_length=2000)
    email_to: str = Field(default="", max_length=320)
    trigger_statuses: list[CallStatusLiteral] = Field(default_factory=lambda: ["completed"])
    include_summary: bool = True
    include_transcript: bool = True
    include_sentiment: bool = False
    include_extracted: bool = False
    enabled: bool = True


class PostCallConfigResponse(BaseModel):
    id: uuid.UUID
    chatbot_id: uuid.UUID
    delivery_method: DeliveryMethodLiteral
    webhook_url: str
    email_to: str
    trigger_statuses: list[CallStatusLiteral]
    include_summary: bool
    include_transcript: bool
    include_sentiment: bool
    include_extracted: bool
    enabled: bool
    created_at: datetime


class PostCallDeliveryResponse(BaseModel):
    id: uuid.UUID
    config_id: uuid.UUID
    session_id: uuid.UUID
    call_status: CallStatusLiteral
    delivery_method: DeliveryMethodLiteral
    destination: str
    status: str
    error: str
    created_at: datetime


class EndSessionRequest(BaseModel):
    """Closes a conversation and fires any matching post-call configs."""

    call_status: CallStatusLiteral = "completed"


class EndSessionResponse(BaseModel):
    session_id: uuid.UUID
    call_status: CallStatusLiteral
    dispatched: int
    skipped: int


# --- Broadcast campaigns ---
RecipientStatusLiteral = Literal["pending", "sent", "delivered", "read", "replied", "failed"]
BroadcastStatusLiteral = Literal["queued", "sending", "paused", "completed"]


class BroadcastRecipientInput(BaseModel):
    phone_number: str = Field(min_length=5, max_length=32)
    display_name: str = Field(default="", max_length=160)


BroadcastModeLiteral = Literal["broadcast", "broadcast_reply"]
SenderKindLiteral = Literal["cloud_api", "personal"]


class CampaignSenderResponse(BaseModel):
    """One WhatsApp number a campaign can send from.

    Cloud API numbers and QR-linked personal accounts are listed together
    because, from the operator's side, both are just "a WhatsApp number I can
    send from" — the difference only matters to the transport.
    """

    id: uuid.UUID
    kind: SenderKindLiteral
    label: str
    phone_number: str
    # False when the sender exists but can't send right now (a personal account
    # that isn't linked, or a bridge that isn't configured). The reason says why.
    available: bool = True
    unavailable_reason: str = ""
    # The assistant already bound to this number, if any.
    chatbot_id: uuid.UUID | None = None
    chatbot_name: str = ""


class CreateBroadcastRequest(BaseModel):
    chatbot_id: uuid.UUID
    name: str = Field(min_length=1, max_length=160)
    message_template: str = Field(min_length=1, max_length=1600)
    mode: BroadcastModeLiteral = "broadcast_reply"
    # Which number to send from. Omitted = fall back to the assistant's own
    # Cloud API channel, which is how campaigns worked before senders existed.
    sender_kind: SenderKindLiteral | None = None
    sender_id: uuid.UUID | None = None
    # Structured contacts, or a pasted CSV/newline blob — the UI offers both and
    # the server normalizes either into recipients.
    recipients: list[BroadcastRecipientInput] = Field(default_factory=list, max_length=5000)
    recipients_text: str = Field(default="", max_length=500_000)


class AddRecipientsRequest(BaseModel):
    recipients: list[BroadcastRecipientInput] = Field(default_factory=list, max_length=5000)
    recipients_text: str = Field(default="", max_length=500_000)


class BroadcastRecipientResponse(BaseModel):
    id: uuid.UUID
    phone_number: str
    display_name: str
    status: RecipientStatusLiteral
    error: str
    session_id: uuid.UUID | None
    attempts: int
    updated_at: datetime


class BroadcastResponse(BaseModel):
    id: uuid.UUID
    chatbot_id: uuid.UUID
    chatbot_name: str
    whatsapp_channel_id: uuid.UUID | None = None
    whatsapp_session_id: uuid.UUID | None = None
    sender_kind: SenderKindLiteral = "cloud_api"
    mode: BroadcastModeLiteral = "broadcast_reply"
    from_number: str
    name: str
    message_template: str
    status: BroadcastStatusLiteral
    total_count: int
    sent_count: int
    delivered_count: int
    read_count: int
    replied_count: int
    failed_count: int
    created_at: datetime
    updated_at: datetime


class RecipientPageResponse(BaseModel):
    """One page of the contacts list, with the funnel counts the filter chips
    render — returned together so the chips can't disagree with the rows."""

    recipients: list[BroadcastRecipientResponse]
    total: int
    page: int
    page_size: int


class AddRecipientsResponse(BaseModel):
    added: int
    duplicates: int
    invalid: list[str]


class BroadcastMessageResponse(BaseModel):
    """One turn of a recipient's conversation, for the Chat Log pane."""

    id: uuid.UUID
    role: Literal["user", "assistant", "system"]
    content: str
    created_at: datetime


class SendManualMessageRequest(BaseModel):
    """Human takeover — send as the assistant, bypassing the RAG pipeline."""

    message: str = Field(min_length=1, max_length=1600)


# --- Integrations catalogue ---
IntegrationCategory = Literal["calendar_crm", "messaging", "data_sheets", "custom_tools"]
IntegrationTiming = Literal["during_call", "post_call"]


class CredentialFieldSchema(BaseModel):
    key: str
    label: str
    placeholder: str = ""
    secret: bool = False
    required: bool = True
    help_text: str = ""


class IntegrationCardResponse(BaseModel):
    """One catalogue card, merged with this tenant's connection state."""

    id: str
    name: str
    description: str
    category: IntegrationCategory
    category_label: str
    timing: IntegrationTiming
    auth: Literal["oauth", "fields"]
    credential_fields: list[CredentialFieldSchema]
    # False = the card renders but Connect is disabled; `unavailable_reason` says why.
    wired: bool
    unavailable_reason: str = ""
    oauth_start_path: str = ""
    connected: bool = False
    enabled: bool = True
    # Secret values are masked — the browser never receives a stored credential.
    config: dict[str, str] = Field(default_factory=dict)
    connected_at: datetime | None = None


class IntegrationCatalogueResponse(BaseModel):
    integrations: list[IntegrationCardResponse]
    # Chip counts, keyed by category plus "all".
    counts: dict[str, int]
    connected_count: int


class ConnectIntegrationRequest(BaseModel):
    # Free-form because each integration declares its own fields; the server
    # keeps only keys the spec names and drops the rest.
    config: dict[str, str] = Field(default_factory=dict)


class IntegrationTestResponse(BaseModel):
    ok: bool
    message: str


# --- Report an issue ---
ReportTypeLiteral = Literal["bug", "feature_request", "question", "billing", "other"]
PriorityLiteral = Literal["low", "medium", "high", "critical"]
IssueStatusLiteral = Literal["open", "in_progress", "resolved", "closed"]


class CreateIssueReportRequest(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    email: EmailStr
    phone: str = Field(default="", max_length=32)
    report_type: ReportTypeLiteral
    priority: PriorityLiteral = "medium"
    subject: str = Field(min_length=1, max_length=200)
    description: str = Field(min_length=1, max_length=5000)
    page_url: str = Field(default="", max_length=500)


class IssueReportResponse(BaseModel):
    id: uuid.UUID
    name: str
    email: str
    phone: str
    report_type: ReportTypeLiteral
    priority: PriorityLiteral
    subject: str
    description: str
    status: IssueStatusLiteral
    page_url: str
    email_sent: bool
    created_at: datetime


class IssueOptionsResponse(BaseModel):
    """Drives the form's dropdowns so the labels live in one place."""

    report_types: list[dict[str, str]]
    priorities: list[dict[str, str]]
    support_email_configured: bool


# --- Cloned voices ---
VoiceGenderLiteral = Literal["female", "male", "neutral"]
VoiceStatusLiteral = Literal["pending", "ready", "failed"]


class VoiceProfileResponse(BaseModel):
    id: uuid.UUID
    name: str
    gender: VoiceGenderLiteral
    language: str
    description: str
    duration_seconds: float
    sample_bytes: int
    provider: str
    status: VoiceStatusLiteral
    error: str
    created_at: datetime


class VoiceOptionsResponse(BaseModel):
    languages: list[dict[str, str]]
    genders: list[dict[str, str]]
    min_seconds: int
    max_seconds: int
    max_mb: int
    # False = samples are still recorded, stored, and listed, but cloning is
    # unavailable. The UI says so rather than failing at submit time.
    cloning_enabled: bool
    provider: str


class SpeakRequest(BaseModel):
    text: str = Field(min_length=1, max_length=2000)


# --- Personal WhatsApp (QR / multi-device) ---
WhatsAppWebStatusLiteral = Literal[
    "pending", "awaiting_scan", "linked", "disconnected", "logged_out", "failed"
]


class WhatsAppWebSessionResponse(BaseModel):
    id: uuid.UUID
    chatbot_id: uuid.UUID | None
    chatbot_name: str = ""
    status: WhatsAppWebStatusLiteral
    phone_number: str
    display_name: str
    # Only populated while a scan is pending and the code is still valid.
    qr_data_url: str = ""
    qr_seconds_remaining: int = 0
    last_error: str = ""
    health: str
    linked_at: datetime | None = None
    created_at: datetime


class WhatsAppWebOptionsResponse(BaseModel):
    """Whether the bridge is configured and reachable, so the Channels page can
    disable the method instead of failing at scan time."""

    enabled: bool
    bridge_healthy: bool
    message: str = ""


class AttachAssistantRequest(BaseModel):
    # Null detaches: messages keep arriving and are stored, nothing replies.
    chatbot_id: uuid.UUID | None = None


class BridgeEventRequest(BaseModel):
    """Posted by the Node bridge. Authenticated by a shared secret header, not
    a JWT — the bridge acts for no particular user."""

    session_id: uuid.UUID
    event: Literal["qr", "linked", "disconnected", "logged_out", "failed", "message"]
    qr_data_url: str = ""
    phone_number: str = ""
    display_name: str = ""
    error: str = ""
    # message events. `from` is a Python keyword, so it arrives via an alias.
    from_: str = Field(default="", alias="from")
    jid: str = ""
    text: str = ""
    message_id: str = ""
    pushname: str = ""

    model_config = {"populate_by_name": True}
