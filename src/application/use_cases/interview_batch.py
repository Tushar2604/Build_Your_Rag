"""Bulk interview invites: create a batch against one job description, attach
many resumes, extract each candidate's identity, and mass-schedule + email
only the rows the admin approved in the review step.

Both sweeps (`ExtractBatchCandidates`, `SendInterviewBatch`) run as
BackgroundTasks with bounded concurrency — the same in-process model
`IngestDocument` already uses for document ingestion, no new task queue.
Progress counters are bumped via `InterviewBatchRepository.increment_counts`
(an atomic SQL increment), not read-modify-write, since candidates process
concurrently.
"""

from __future__ import annotations

import asyncio
from datetime import datetime

import structlog

from src.application.ports.repositories import UnitOfWork
from src.application.ports.services import LLMProvider
from src.application.use_cases._interview_shared import (
    build_invite_html,
    extract_candidate_identity,
    generate_interview_questions,
)
from src.domain.document.entities import IngestionStatus
from src.domain.interview.batch_entities import BatchCandidate, InterviewBatch
from src.domain.interview.entities import Interview
from src.domain.shared.errors import InvalidStateError, NotFoundError
from src.domain.shared.identifiers import BatchCandidateId, DocumentId, InterviewBatchId, TenantId
from src.infrastructure.email.resend import ResendEmailSender

log = structlog.get_logger(__name__)

# Enough to meaningfully speed up a batch of thousands without hammering the
# LLM/embedding/email provider all at once.
_CONCURRENCY = 5
# How long ExtractBatchCandidates waits for one resume's ingestion to finish
# before giving up on that candidate.
_INGEST_WAIT_TIMEOUT_S = 300
_INGEST_POLL_INTERVAL_S = 2


class CreateInterviewBatch:
    def __init__(self, uow: UnitOfWork) -> None:
        self._uow = uow

    async def execute(
        self,
        tenant_id: TenantId,
        *,
        role_title: str,
        job_document_id: DocumentId,
        window_opens_at: datetime,
        window_closes_at: datetime | None,
    ) -> InterviewBatch:
        async with self._uow as uow:
            uow.set_tenant_scope(tenant_id)
            doc = await uow.documents.get(tenant_id, job_document_id)
            if doc is None:
                raise NotFoundError(f"Document {job_document_id} not found.")
            if doc.status != IngestionStatus.READY:
                raise InvalidStateError(f"Job description is not ready yet (status={doc.status}).")
            batch = InterviewBatch(
                tenant_id=tenant_id,
                role_title=role_title,
                job_document_id=job_document_id,
                window_opens_at=window_opens_at,
                window_closes_at=window_closes_at,
            )
            await uow.interview_batches.add(batch)
            await uow.commit()
        return batch


class AttachBatchResume:
    def __init__(self, uow: UnitOfWork) -> None:
        self._uow = uow

    async def execute(
        self,
        tenant_id: TenantId,
        batch_id: InterviewBatchId,
        resume_document_id: DocumentId,
        resume_filename: str,
    ) -> BatchCandidate:
        async with self._uow as uow:
            uow.set_tenant_scope(tenant_id)
            batch = await uow.interview_batches.get(tenant_id, batch_id)
            if batch is None:
                raise NotFoundError(f"Batch {batch_id} not found.")
            candidate = BatchCandidate(
                tenant_id=tenant_id,
                batch_id=batch_id,
                resume_document_id=resume_document_id,
                resume_filename=resume_filename,
            )
            await uow.batch_candidates.add(candidate)
            await uow.interview_batches.increment_counts(tenant_id, batch_id, total=1)
            await uow.commit()
        return candidate


class ExtractBatchCandidates:
    """Background sweep: wait for each candidate's resume to finish
    ingesting, then extract name/email from it in one LLM call."""

    def __init__(self, uow: UnitOfWork, llm: LLMProvider) -> None:
        self._uow = uow
        self._llm = llm

    async def execute(self, tenant_id: TenantId, batch_id: InterviewBatchId) -> None:
        async with self._uow as uow:
            uow.set_tenant_scope(tenant_id)
            candidates = await uow.batch_candidates.list_for_batch(tenant_id, batch_id)
        pending = [c for c in candidates if c.status == "ingesting"]
        semaphore = asyncio.Semaphore(_CONCURRENCY)

        async def process(candidate: BatchCandidate) -> None:
            async with semaphore:
                await self._process_one(tenant_id, candidate)

        await asyncio.gather(*(process(c) for c in pending))

    async def _process_one(self, tenant_id: TenantId, candidate: BatchCandidate) -> None:
        try:
            resume_text = await self._wait_for_resume(tenant_id, candidate.resume_document_id)
        except (TimeoutError, ValueError) as exc:
            candidate.status = "failed"
            candidate.error = str(exc)[:500] or "Resume processing timed out."
            await self._save(tenant_id, candidate)
            return

        try:
            name, email = await extract_candidate_identity(self._llm, resume_text)
        except Exception:  # noqa: BLE001 - extraction failure shouldn't kill the whole sweep
            log.warning("interview_batch.extract_failed", candidate_id=str(candidate.id))
            name, email = "", ""
        candidate.candidate_name = name
        candidate.candidate_email = email
        candidate.status = "needs_review"
        await self._save(tenant_id, candidate)

    async def _wait_for_resume(self, tenant_id: TenantId, document_id: DocumentId) -> str:
        waited = 0
        while True:
            async with self._uow as uow:
                uow.set_tenant_scope(tenant_id)
                doc = await uow.documents.get(tenant_id, document_id)
                if doc is None:
                    raise ValueError("Resume document not found.")
                if doc.status == IngestionStatus.FAILED:
                    raise ValueError(doc.error or "Resume processing failed.")
                if doc.status == IngestionStatus.READY:
                    chunks = await uow.chunks.list_for_document(tenant_id, document_id)
                    return "\n\n".join(c.text for c in chunks)
            if waited >= _INGEST_WAIT_TIMEOUT_S:
                raise TimeoutError("Resume processing timed out.")
            await asyncio.sleep(_INGEST_POLL_INTERVAL_S)
            waited += _INGEST_POLL_INTERVAL_S

    async def _save(self, tenant_id: TenantId, candidate: BatchCandidate) -> None:
        async with self._uow as uow:
            uow.set_tenant_scope(tenant_id)
            await uow.batch_candidates.update(candidate)
            await uow.commit()


class UpdateBatchCandidate:
    """Admin edits a row before sending — fix a bad email/name, or exclude it."""

    def __init__(self, uow: UnitOfWork) -> None:
        self._uow = uow

    async def execute(
        self,
        tenant_id: TenantId,
        candidate_id: BatchCandidateId,
        *,
        candidate_name: str | None = None,
        candidate_email: str | None = None,
        excluded: bool | None = None,
    ) -> BatchCandidate:
        async with self._uow as uow:
            uow.set_tenant_scope(tenant_id)
            candidate = await uow.batch_candidates.get(tenant_id, candidate_id)
            if candidate is None:
                raise NotFoundError(f"Candidate {candidate_id} not found.")
            if candidate_name is not None:
                candidate.candidate_name = candidate_name.strip()[:200]
            if candidate_email is not None:
                candidate.candidate_email = candidate_email.strip()[:320]
            if excluded is True:
                candidate.status = "excluded"
            elif excluded is False and candidate.status == "excluded":
                candidate.status = "needs_review"
            await uow.batch_candidates.update(candidate)
            await uow.commit()
        return candidate


class SendInterviewBatch:
    """Background sweep: turn every reviewable, valid-email candidate into a
    real Interview and best-effort email them the join link."""

    def __init__(
        self, uow: UnitOfWork, llm: LLMProvider, email: ResendEmailSender, frontend_base_url: str
    ) -> None:
        self._uow = uow
        self._llm = llm
        self._email = email
        self._frontend_base = frontend_base_url.rstrip("/")

    async def execute(self, tenant_id: TenantId, batch_id: InterviewBatchId) -> None:
        async with self._uow as uow:
            uow.set_tenant_scope(tenant_id)
            batch = await uow.interview_batches.get(tenant_id, batch_id)
            if batch is None:
                raise NotFoundError(f"Batch {batch_id} not found.")
            batch.status = "sending"
            await uow.interview_batches.update(batch)
            candidates = await uow.batch_candidates.list_for_batch(tenant_id, batch_id)
            job_chunks = await uow.chunks.list_for_document(tenant_id, batch.job_document_id)
            await uow.commit()
        job_text = "\n\n".join(c.text for c in job_chunks)

        sendable = [c for c in candidates if c.sendable()]
        semaphore = asyncio.Semaphore(_CONCURRENCY)

        async def process(candidate: BatchCandidate) -> None:
            async with semaphore:
                await self._process_one(tenant_id, batch, job_text, candidate)

        await asyncio.gather(*(process(c) for c in sendable))

        async with self._uow as uow:
            uow.set_tenant_scope(tenant_id)
            fresh = await uow.interview_batches.get(tenant_id, batch_id)
            if fresh is not None:
                fresh.status = "completed"
                await uow.interview_batches.update(fresh)
                await uow.commit()

    async def _process_one(
        self, tenant_id: TenantId, batch: InterviewBatch, job_text: str, candidate: BatchCandidate
    ) -> None:
        try:
            async with self._uow as uow:
                uow.set_tenant_scope(tenant_id)
                resume_chunks = await uow.chunks.list_for_document(tenant_id, candidate.resume_document_id)
            resume_text = "\n\n".join(c.text for c in resume_chunks)
            questions = await generate_interview_questions(self._llm, job_text, resume_text)

            interview = Interview(
                tenant_id=tenant_id,
                candidate_name=candidate.candidate_name,
                candidate_email=candidate.candidate_email,
                role_title=batch.role_title,
                job_document_id=batch.job_document_id,
                resume_document_id=candidate.resume_document_id,
                scheduled_at=batch.window_opens_at,
                window_closes_at=batch.window_closes_at,
                questions=questions,
            )
            async with self._uow as uow:
                uow.set_tenant_scope(tenant_id)
                await uow.interviews.add(interview)
                await uow.commit()

            if self._email.enabled:
                join_url = f"{self._frontend_base}/interview/{interview.access_token}"
                try:
                    await self._email.send(
                        to=interview.candidate_email,
                        subject=f"Your interview for {batch.role_title or 'the role'}",
                        html=build_invite_html(interview, join_url),
                    )
                except Exception:  # noqa: BLE001 - email is best-effort, doesn't fail scheduling
                    log.warning("interview_batch.email_failed", candidate_id=str(candidate.id))

            candidate.status = "scheduled"
            candidate.interview_id = interview.id
            candidate.error = None
            await self._finish(tenant_id, batch.id, candidate, sent=True)
        except Exception as exc:  # noqa: BLE001 - one candidate's failure shouldn't kill the sweep
            log.exception("interview_batch.schedule_failed", candidate_id=str(candidate.id))
            candidate.status = "failed"
            candidate.error = str(exc)[:500]
            await self._finish(tenant_id, batch.id, candidate, sent=False)

    async def _finish(
        self, tenant_id: TenantId, batch_id: InterviewBatchId, candidate: BatchCandidate, *, sent: bool
    ) -> None:
        async with self._uow as uow:
            uow.set_tenant_scope(tenant_id)
            await uow.batch_candidates.update(candidate)
            await uow.interview_batches.increment_counts(
                tenant_id, batch_id, sent=1 if sent else 0, failed=0 if sent else 1
            )
            await uow.commit()
