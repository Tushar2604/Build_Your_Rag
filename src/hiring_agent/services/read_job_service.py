"""ReadJobService — ingest a job description and extract its Job Context.

Reuses the existing chatbot ingestion pipeline end to end. There is NO new
parsing, chunking, or embedding code here — the heavy lifting is delegated to
the very use cases the document-upload API uses:

    CreateUpload   -> creates the Document record + enforces tenant quotas
    put_bytes      -> writes the source straight to object storage
    CompleteUpload -> marks the document UPLOADED
    IngestDocument -> PARSE -> CHUNK -> EMBED -> STORE (pgvector)

The chunks land in the same tenant-scoped corpus as any other document, so a
job description is immediately searchable by the rest of the platform. On top
of that pipeline this service adds one thing: a single LLM call that distils
the parsed text into a structured `JobContext`.
"""

from __future__ import annotations

import json
from collections.abc import Callable

import structlog

from src.application.dtos import CreateUploadInput
from src.application.ports.repositories import UnitOfWork
from src.application.ports.services import (
    Chunker,
    DocumentParser,
    Embedder,
    LLMProvider,
    ObjectStorage,
)
from src.application.use_cases.documents import CompleteUpload, CreateUpload
from src.application.use_cases.ingest_document import IngestDocument
from src.domain.document.entities import IngestionStatus
from src.domain.shared.identifiers import DocumentId, TenantId
from src.hiring_agent.prompts.read_job import (
    READ_JOB_SYSTEM,
    build_read_job_user_prompt,
)
from src.hiring_agent.types import JobContext, ReadJobResult

log = structlog.get_logger(__name__)


class ReadJobService:
    """Ingest a job description (PDF or text) and return its Job Context."""

    def __init__(
        self,
        uow_factory: Callable[[], UnitOfWork],
        storage: ObjectStorage,
        parser: DocumentParser,
        chunker: Chunker,
        embedder: Embedder,
        llm: LLMProvider,
    ) -> None:
        # A factory (not a single instance): each reused use case opens and
        # closes its own unit of work, so it needs a fresh one.
        self._uow_factory = uow_factory
        self._storage = storage
        self._parser = parser
        self._chunker = chunker
        self._embedder = embedder
        self._llm = llm

    async def execute(
        self,
        tenant_id: TenantId,
        *,
        text: str | None = None,
        pdf_bytes: bytes | None = None,
        filename: str | None = None,
        content_type: str | None = None,
    ) -> ReadJobResult:
        data, content_type, filename = self._normalize_input(
            text, pdf_bytes, filename, content_type
        )

        # 1. Create the Document record (reuses quota + limit enforcement).
        create = CreateUpload(self._uow_factory(), self._storage)
        upload = await create.execute(
            tenant_id,
            CreateUploadInput(
                filename=filename,
                content_type=content_type,
                size_bytes=len(data),
            ),
        )
        document_id = DocumentId(upload.document_id)

        # 2. Write the source bytes straight to storage (we already hold them,
        #    so we bypass the presigned-URL round trip the HTTP flow uses).
        await self._storage.put_bytes(upload.storage_key, data, content_type)

        # 3. Mark UPLOADED, then run the full ingestion pipeline (parse, chunk,
        #    embed, store) — identical to how any uploaded document is processed.
        await CompleteUpload(self._uow_factory()).execute(tenant_id, document_id)
        ingest = IngestDocument(
            self._uow_factory(),
            self._storage,
            self._parser,
            self._chunker,
            self._embedder,
        )
        await ingest.execute(tenant_id, document_id)

        # 4. Read back the ingested document's terminal state.
        async with self._uow_factory() as uow:
            uow.set_tenant_scope(tenant_id)
            doc = await uow.documents.get(tenant_id, document_id)

        status = str(doc.status) if doc else "unknown"
        chunk_count = doc.chunk_count if doc else 0

        if doc is None or doc.status == IngestionStatus.FAILED:
            reason = (
                (doc.error if doc else "document vanished after ingestion")
                or "ingestion failed"
            )
            log.warning(
                "read_job.ingest_failed",
                tenant=str(tenant_id),
                document_id=str(document_id),
                reason=reason,
            )
            return ReadJobResult(
                document_id=str(document_id),
                chunk_count=chunk_count,
                status=status,
                job_context=JobContext(),
                extraction_note=f"Ingestion did not complete: {reason}",
            )

        # 5. Extract the structured Job Context from the parsed text. Parsing
        #    again here is cheap and deterministic; embedding is NOT repeated.
        parsed_text = await self._parser.extract_text(data, content_type, filename)
        job_context, note = await self._extract_context(parsed_text)

        log.info(
            "read_job.ready",
            tenant=str(tenant_id),
            document_id=str(document_id),
            chunks=chunk_count,
            required_skills=len(job_context.required_skills),
        )
        return ReadJobResult(
            document_id=str(document_id),
            chunk_count=chunk_count,
            status=status,
            job_context=job_context,
            extraction_note=note,
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _normalize_input(
        text: str | None,
        pdf_bytes: bytes | None,
        filename: str | None,
        content_type: str | None,
    ) -> tuple[bytes, str, str]:
        """Resolve the input into (bytes, content_type, filename)."""
        if pdf_bytes:
            return (
                pdf_bytes,
                content_type or "application/pdf",
                filename or "job-description.pdf",
            )
        if text and text.strip():
            return (
                text.encode("utf-8"),
                content_type or "text/plain",
                filename or "job-description.txt",
            )
        raise ValueError("Provide a non-empty `text` or `pdf_bytes` job description.")

    async def _extract_context(self, job_text: str) -> tuple[JobContext, str | None]:
        """Run the LLM extraction. Never raises — degrades to an empty context."""
        try:
            result = await self._llm.generate(
                READ_JOB_SYSTEM, build_read_job_user_prompt(job_text)
            )
        except Exception as exc:  # noqa: BLE001 - extraction is best-effort
            log.warning("read_job.llm_failed", error=str(exc))
            return JobContext(), f"Extraction unavailable: {exc}"

        payload = self._parse_json_object(result.text)
        if payload is None:
            return JobContext(), "Model returned no parseable JSON; context empty."

        try:
            context = JobContext(
                title=str(payload.get("title", "")),
                required_skills=_as_str_list(payload.get("required_skills")),
                experience=str(payload.get("experience", "")),
                responsibilities=_as_str_list(payload.get("responsibilities")),
                preferred_skills=_as_str_list(payload.get("preferred_skills")),
                interview_stages=_as_str_list(payload.get("interview_stages")),
            )
        except Exception as exc:  # noqa: BLE001 - malformed field shapes
            log.warning("read_job.context_shape_error", error=str(exc))
            return JobContext(), f"Malformed extraction payload: {exc}"

        return context, None

    @staticmethod
    def _parse_json_object(raw: str) -> dict | None:
        """Best-effort extraction of a JSON object from an LLM response.

        Handles bare JSON, ```json code fences, and leading/trailing prose by
        slicing between the first '{' and the last '}'.
        """
        text = raw.strip()
        if text.startswith("```"):
            # Strip a fenced block: ```json ... ``` or ``` ... ```
            text = text.strip("`")
            if text[:4].lower() == "json":
                text = text[4:]
        try:
            parsed = json.loads(text)
            return parsed if isinstance(parsed, dict) else None
        except json.JSONDecodeError:
            pass

        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end > start:
            try:
                parsed = json.loads(text[start : end + 1])
                return parsed if isinstance(parsed, dict) else None
            except json.JSONDecodeError:
                return None
        return None


def _as_str_list(value: object) -> list[str]:
    """Coerce a model field into a clean list[str]."""
    if isinstance(value, list):
        return [str(v).strip() for v in value if str(v).strip()]
    if isinstance(value, str) and value.strip():
        # Tolerate a comma-separated string where a list was expected.
        return [part.strip() for part in value.split(",") if part.strip()]
    return []
