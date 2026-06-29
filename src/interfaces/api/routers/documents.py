"""Document endpoints: upload lifecycle, status, retry, delete.

Ingestion runs as a FastAPI BackgroundTask after the response is returned. The
task is resumable (see IngestDocument), so a host sleep mid-job is recoverable.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, BackgroundTasks, HTTPException, Response

from src.application.dtos import CreateUploadInput
from src.application.use_cases.documents import CompleteUpload, CreateUpload
from src.application.use_cases.ingest_document import IngestDocument
from src.config.container import get_container
from src.domain.document.entities import IngestionStatus
from src.domain.shared.identifiers import DocumentId, TenantId
from src.interfaces.api.deps import ContainerDep, PrincipalDep
from src.interfaces.api.schemas import (
    CreateUploadRequest,
    CreateUploadResponse,
    DocumentResponse,
)

router = APIRouter(prefix="/documents", tags=["documents"])


async def _run_ingestion(tenant_id: TenantId, document_id: DocumentId) -> None:
    """Background entrypoint — builds its own container/UoW (no request scope)."""
    container = get_container()
    use_case = IngestDocument(
        container.unit_of_work(),
        container.storage,
        container.parser,
        container.chunker,
        container.embedder,
    )
    await use_case.execute(tenant_id, document_id)


@router.post("", response_model=CreateUploadResponse, status_code=201)
async def create_upload(
    body: CreateUploadRequest, principal: PrincipalDep, container: ContainerDep
) -> CreateUploadResponse:
    use_case = CreateUpload(container.unit_of_work(), container.storage)
    result = await use_case.execute(
        principal.tenant_id,
        CreateUploadInput(
            filename=body.filename,
            content_type=body.content_type,
            size_bytes=body.size_bytes,
        ),
    )
    return CreateUploadResponse(
        document_id=result.document_id,
        upload_url=result.upload_url,
        storage_key=result.storage_key,
    )


@router.post("/{document_id}/complete", status_code=202)
async def complete_upload(
    document_id: uuid.UUID,
    principal: PrincipalDep,
    container: ContainerDep,
    background: BackgroundTasks,
) -> dict[str, str]:
    use_case = CompleteUpload(container.unit_of_work())
    tenant_id, doc_id = await use_case.execute(
        principal.tenant_id, DocumentId(document_id)
    )
    background.add_task(_run_ingestion, tenant_id, doc_id)
    return {"status": "ingestion_scheduled"}


@router.get("", response_model=list[DocumentResponse])
async def list_documents(
    principal: PrincipalDep, container: ContainerDep
) -> list[DocumentResponse]:
    async with container.unit_of_work() as uow:
        uow.set_tenant_scope(principal.tenant_id)
        docs = await uow.documents.list_for_tenant(principal.tenant_id)
    return [
        DocumentResponse(
            id=d.id, filename=d.filename, status=d.status.value,
            chunk_count=d.chunk_count, error=d.error,
        )
        for d in docs
    ]


@router.get("/{document_id}", response_model=DocumentResponse)
async def get_document(
    document_id: uuid.UUID, principal: PrincipalDep, container: ContainerDep
) -> DocumentResponse:
    async with container.unit_of_work() as uow:
        uow.set_tenant_scope(principal.tenant_id)
        doc = await uow.documents.get(principal.tenant_id, DocumentId(document_id))
    if doc is None:
        raise HTTPException(status_code=404, detail="Document not found")
    return DocumentResponse(
        id=doc.id, filename=doc.filename, status=doc.status.value,
        chunk_count=doc.chunk_count, error=doc.error,
    )


@router.post("/{document_id}/retry", status_code=202)
async def retry_document(
    document_id: uuid.UUID,
    principal: PrincipalDep,
    container: ContainerDep,
    background: BackgroundTasks,
) -> dict[str, str]:
    async with container.unit_of_work() as uow:
        uow.set_tenant_scope(principal.tenant_id)
        doc = await uow.documents.get(principal.tenant_id, DocumentId(document_id))
        if doc is None:
            raise HTTPException(status_code=404, detail="Document not found")
        if doc.status == IngestionStatus.FAILED:
            doc.transition_to(IngestionStatus.UPLOADED)
            await uow.documents.update(doc)
        await uow.commit()
    background.add_task(_run_ingestion, principal.tenant_id, DocumentId(document_id))
    return {"status": "ingestion_scheduled"}


@router.delete("/{document_id}", status_code=204, response_class=Response)
async def delete_document(
    document_id: uuid.UUID, principal: PrincipalDep, container: ContainerDep
) -> Response:
    async with container.unit_of_work() as uow:
        uow.set_tenant_scope(principal.tenant_id)
        doc = await uow.documents.get(principal.tenant_id, DocumentId(document_id))
        if doc is None:
            raise HTTPException(status_code=404, detail="Document not found")
        await uow.chunks.delete_for_document(principal.tenant_id, DocumentId(document_id))
        await container.storage.delete(doc.storage_key)
        await uow.documents.delete(principal.tenant_id, DocumentId(document_id))
        await uow.commit()
    return Response(status_code=204)
