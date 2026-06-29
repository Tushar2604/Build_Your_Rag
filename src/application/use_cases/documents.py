"""Document upload lifecycle: request a presigned URL, then complete the upload.

Bytes go straight to object storage via the presigned URL and never transit the
API process — essential on small free instances with little memory.
"""

from __future__ import annotations

from pathlib import PurePosixPath

from src.application.dtos import CreateUploadInput, CreateUploadOutput
from src.application.ports.repositories import UnitOfWork
from src.application.ports.services import ObjectStorage
from src.config import get_settings
from src.domain.document.entities import Document, IngestionStatus
from src.domain.document.events import DocumentUploaded
from src.domain.shared.errors import NotFoundError, QuotaExceededError
from src.domain.shared.identifiers import DocumentId, TenantId, new_id


def _storage_ext(filename: str) -> str:
    """A short, safe extension for the storage key. The original filename is kept
    on the Document record (and used by the parser); the storage key only needs to
    be unique and filesystem/R2-safe — so we never embed the raw filename, which
    can be long enough to blow past Windows' 260-char path limit or contain
    spaces/odd characters."""
    suffix = PurePosixPath(filename.replace("\\", "/")).suffix.lower()
    return suffix if 1 < len(suffix) <= 10 and suffix[1:].isalnum() else ""


class CreateUpload:
    def __init__(self, uow: UnitOfWork, storage: ObjectStorage) -> None:
        self._uow = uow
        self._storage = storage

    async def execute(
        self, tenant_id: TenantId, data: CreateUploadInput
    ) -> CreateUploadOutput:
        settings = get_settings()
        max_bytes = settings.max_upload_mb * 1024 * 1024
        if data.size_bytes > max_bytes:
            raise QuotaExceededError(
                f"File exceeds the {settings.max_upload_mb} MB limit."
            )

        async with self._uow as uow:
            uow.set_tenant_scope(tenant_id)
            tenant = await uow.tenants.get(tenant_id)
            if tenant is None:
                raise NotFoundError("Tenant not found.")
            count = await uow.documents.count_for_tenant(tenant_id)
            if count >= tenant.max_documents:
                raise QuotaExceededError("Document limit reached for this tenant.")

            # Generate the id up front so the storage key is stable. The key uses
            # the doc id (already unique) + a safe extension — NOT the raw
            # filename, which may be long/space-laden (the display name lives on
            # the `filename` field).
            doc_id = DocumentId(new_id())
            doc = Document(
                id=doc_id,
                tenant_id=tenant_id,
                filename=data.filename,
                content_type=data.content_type,
                size_bytes=data.size_bytes,
                storage_key=f"{tenant_id}/{doc_id}/source{_storage_ext(data.filename)}",
                checksum="",
            )
            await uow.documents.add(doc)
            await uow.commit()

        url = await self._storage.presign_put(doc.storage_key, data.content_type, max_bytes)
        return CreateUploadOutput(
            document_id=doc.id, upload_url=url, storage_key=doc.storage_key
        )


class CompleteUpload:
    """Mark bytes as uploaded and signal the ingestion pipeline to run.

    Returns the (tenant_id, document_id) so the interface layer can schedule the
    background ingestion task after the response is sent.
    """

    def __init__(self, uow: UnitOfWork) -> None:
        self._uow = uow

    async def execute(
        self, tenant_id: TenantId, document_id: DocumentId
    ) -> tuple[TenantId, DocumentId]:
        async with self._uow as uow:
            uow.set_tenant_scope(tenant_id)
            doc = await uow.documents.get(tenant_id, document_id)
            if doc is None:
                raise NotFoundError("Document not found.")
            if doc.status == IngestionStatus.PENDING:
                doc.transition_to(IngestionStatus.UPLOADED)
                await uow.documents.update(doc)
                uow.collect_event(
                    DocumentUploaded(
                        tenant_id=tenant_id, document_id=doc.id, filename=doc.filename
                    )
                )
            await uow.commit()
        return tenant_id, document_id
