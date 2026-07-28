"""Bulk interview invites: one job description, many resumes, one send.

`InterviewBatch` is the orchestration record; each resume gets its own
`BatchCandidate` row tracking it through extraction and (optionally)
scheduling. A `BatchCandidate` that gets scheduled produces a normal
`Interview` row — batches don't replace the Interview aggregate, they're a
staging area in front of it so an admin can bulk-upload resumes, review the
AI-extracted name/email per candidate, and only then trigger a mass send.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Literal

from src.domain.shared.identifiers import (
    BatchCandidateId,
    DocumentId,
    InterviewBatchId,
    InterviewId,
    TenantId,
    new_id,
)

BatchStatus = Literal["collecting", "sending", "completed"]
CandidateStatus = Literal["ingesting", "needs_review", "excluded", "scheduled", "failed"]


@dataclass
class BatchCandidate:
    tenant_id: TenantId
    batch_id: InterviewBatchId
    resume_document_id: DocumentId
    resume_filename: str
    id: BatchCandidateId = field(default_factory=lambda: BatchCandidateId(new_id()))
    candidate_name: str = ""
    candidate_email: str = ""
    status: CandidateStatus = "ingesting"
    error: str | None = None
    interview_id: InterviewId | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def has_valid_email(self) -> bool:
        return "@" in self.candidate_email and "." in self.candidate_email.split("@")[-1]

    def sendable(self) -> bool:
        return self.status == "needs_review" and self.has_valid_email()


@dataclass
class InterviewBatch:
    tenant_id: TenantId
    role_title: str
    job_document_id: DocumentId
    window_opens_at: datetime
    id: InterviewBatchId = field(default_factory=lambda: InterviewBatchId(new_id()))
    window_closes_at: datetime | None = None
    status: BatchStatus = "collecting"
    total_count: int = 0
    sent_count: int = 0
    failed_count: int = 0
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
