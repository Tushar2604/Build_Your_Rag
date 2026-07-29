"""Bulk interview invites — admin (authenticated) CRUD + two background
sweeps. Kept as its own router rather than folding into `interviews.py`,
which already carries the sizable candidate-facing conduct flow.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, BackgroundTasks, HTTPException

from src.application.use_cases.interview_batch import (
    AttachBatchResume,
    CreateInterviewBatch,
    ExtractBatchCandidates,
    SendInterviewBatch,
    UpdateBatchCandidate,
)
from src.config.container import get_container
from src.config.settings import get_settings
from src.domain.interview.batch_entities import BatchCandidate, InterviewBatch
from src.domain.shared.identifiers import BatchCandidateId, DocumentId, InterviewBatchId, TenantId
from src.interfaces.api.deps import AdminPrincipalDep, ContainerDep
from src.interfaces.api.schemas import (
    AttachBatchResumeRequest,
    BatchCandidateResponse,
    CreateBatchRequest,
    InterviewBatchResponse,
    PatchBatchCandidateRequest,
)

router = APIRouter(prefix="/interview-batches", tags=["interview-batches"])


def _candidate_response(c: BatchCandidate) -> BatchCandidateResponse:
    return BatchCandidateResponse(
        id=c.id,
        resume_filename=c.resume_filename,
        candidate_name=c.candidate_name,
        candidate_email=c.candidate_email,
        status=c.status,  # type: ignore[arg-type]
        error=c.error,
        interview_id=c.interview_id,
    )


def _batch_response(
    batch: InterviewBatch, candidates: list[BatchCandidate] | None = None
) -> InterviewBatchResponse:
    return InterviewBatchResponse(
        id=batch.id,
        role_title=batch.role_title,
        job_document_id=batch.job_document_id,
        window_opens_at=batch.window_opens_at,
        window_closes_at=batch.window_closes_at,
        custom_questions=list(batch.custom_questions),
        status=batch.status,  # type: ignore[arg-type]
        total_count=batch.total_count,
        sent_count=batch.sent_count,
        failed_count=batch.failed_count,
        candidates=[_candidate_response(c) for c in (candidates or [])],
    )


async def _run_extraction(tenant_id: TenantId, batch_id: InterviewBatchId) -> None:
    """Background entrypoint — builds its own container/UoW (no request scope)."""
    container = get_container()
    use_case = ExtractBatchCandidates(container.unit_of_work(), container.llm)
    await use_case.execute(tenant_id, batch_id)


async def _run_send(tenant_id: TenantId, batch_id: InterviewBatchId) -> None:
    container = get_container()
    settings = get_settings()
    use_case = SendInterviewBatch(
        container.unit_of_work(), container.llm, container.email, settings.public_frontend_base
    )
    await use_case.execute(tenant_id, batch_id)


@router.post("", response_model=InterviewBatchResponse, status_code=201)
async def create_batch(
    body: CreateBatchRequest, principal: AdminPrincipalDep, container: ContainerDep
) -> InterviewBatchResponse:
    use_case = CreateInterviewBatch(container.unit_of_work())
    batch = await use_case.execute(
        principal.tenant_id,
        role_title=body.role_title,
        job_document_id=DocumentId(body.job_document_id),
        window_opens_at=body.window_opens_at,
        window_closes_at=body.window_closes_at,
        custom_questions=body.custom_questions,
    )
    return _batch_response(batch)


@router.get("", response_model=list[InterviewBatchResponse])
async def list_batches(principal: AdminPrincipalDep, container: ContainerDep) -> list[InterviewBatchResponse]:
    async with container.unit_of_work() as uow:
        uow.set_tenant_scope(principal.tenant_id)
        batches = await uow.interview_batches.list_for_tenant(principal.tenant_id)
    return [_batch_response(b) for b in batches]


@router.get("/{batch_id}", response_model=InterviewBatchResponse)
async def get_batch(
    batch_id: uuid.UUID, principal: AdminPrincipalDep, container: ContainerDep
) -> InterviewBatchResponse:
    async with container.unit_of_work() as uow:
        uow.set_tenant_scope(principal.tenant_id)
        batch = await uow.interview_batches.get(principal.tenant_id, InterviewBatchId(batch_id))
        if batch is None:
            raise HTTPException(status_code=404, detail="Batch not found")
        candidates = await uow.batch_candidates.list_for_batch(principal.tenant_id, InterviewBatchId(batch_id))
    return _batch_response(batch, candidates)


@router.post("/{batch_id}/resumes", response_model=BatchCandidateResponse, status_code=201)
async def attach_resume(
    batch_id: uuid.UUID, body: AttachBatchResumeRequest, principal: AdminPrincipalDep, container: ContainerDep
) -> BatchCandidateResponse:
    use_case = AttachBatchResume(container.unit_of_work())
    candidate = await use_case.execute(
        principal.tenant_id,
        InterviewBatchId(batch_id),
        DocumentId(body.resume_document_id),
        body.resume_filename,
    )
    return _candidate_response(candidate)


@router.post("/{batch_id}/extract", status_code=202)
async def extract_candidates(
    batch_id: uuid.UUID, principal: AdminPrincipalDep, background: BackgroundTasks
) -> dict[str, str]:
    background.add_task(_run_extraction, principal.tenant_id, InterviewBatchId(batch_id))
    return {"status": "extraction_scheduled"}


@router.patch("/{batch_id}/candidates/{candidate_id}", response_model=BatchCandidateResponse)
async def update_candidate(
    batch_id: uuid.UUID,
    candidate_id: uuid.UUID,
    body: PatchBatchCandidateRequest,
    principal: AdminPrincipalDep,
    container: ContainerDep,
) -> BatchCandidateResponse:
    use_case = UpdateBatchCandidate(container.unit_of_work())
    candidate = await use_case.execute(
        principal.tenant_id,
        BatchCandidateId(candidate_id),
        candidate_name=body.candidate_name,
        candidate_email=body.candidate_email,
        excluded=body.excluded,
    )
    return _candidate_response(candidate)


@router.post("/{batch_id}/send", status_code=202)
async def send_batch(
    batch_id: uuid.UUID, principal: AdminPrincipalDep, background: BackgroundTasks
) -> dict[str, str]:
    background.add_task(_run_send, principal.tenant_id, InterviewBatchId(batch_id))
    return {"status": "send_scheduled"}
