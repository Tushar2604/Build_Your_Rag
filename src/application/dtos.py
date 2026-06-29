"""Use-case input/output DTOs (Pydantic v2).

These are the typed contracts between the interface layer and use cases. They
are deliberately separate from both domain entities and API schemas so each can
evolve independently.
"""

from __future__ import annotations

import uuid

from pydantic import BaseModel, EmailStr, Field


class RegisterTenantInput(BaseModel):
    tenant_name: str = Field(min_length=2, max_length=120)
    owner_email: EmailStr
    password: str = Field(min_length=8, max_length=128)


class AuthOutput(BaseModel):
    access_token: str
    refresh_token: str
    tenant_id: uuid.UUID
    user_id: uuid.UUID


class CreateUploadInput(BaseModel):
    filename: str = Field(min_length=1, max_length=255)
    content_type: str
    size_bytes: int = Field(gt=0)


class CreateUploadOutput(BaseModel):
    document_id: uuid.UUID
    upload_url: str
    storage_key: str


class AskInput(BaseModel):
    message: str = Field(min_length=1, max_length=8000)


class CitationOut(BaseModel):
    document_id: uuid.UUID
    chunk_id: str
    ordinal: int
    score: float
    snippet: str


class AnswerOutput(BaseModel):
    message_id: uuid.UUID
    answer: str
    citations: list[CitationOut]
    tokens_used: int
    provider: str


class AgentAskInput(BaseModel):
    message: str = Field(min_length=1, max_length=8000)
    # Cap on agent reasoning steps for this request (server still hard-bounds it).
    max_steps: int = Field(default=6, ge=1, le=12)


class AgentStepOut(BaseModel):
    index: int
    thought: str
    action: str
    observation: str
    model: str


class AgentAnswerOutput(BaseModel):
    """Agent answer plus the trace — the trace is part of the contract so callers
    (and the eval/observability tooling) can inspect how the answer was reached."""

    answer: str
    citations: list[CitationOut]
    tokens_used: int
    provider: str | None
    stop_reason: str
    tools_used: list[str]
    steps: list[AgentStepOut]
