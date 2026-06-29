"""Document aggregate and its ingestion lifecycle.

Ingestion is a resumable state machine. Each state transition is explicit so
that, on a free host that may sleep mid-job, a resume sweep can pick up exactly
where it left off rather than restarting from scratch.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum

from src.domain.shared.errors import InvalidStateError
from src.domain.shared.identifiers import DocumentId, TenantId, new_id


class IngestionStatus(StrEnum):
    PENDING = "pending"        # record created, awaiting upload completion
    UPLOADED = "uploaded"      # bytes in object storage, ready to process
    PARSING = "parsing"
    CHUNKING = "chunking"
    EMBEDDING = "embedding"
    READY = "ready"            # searchable
    FAILED = "failed"


# Allowed forward transitions for the ingestion state machine.
_TRANSITIONS: dict[IngestionStatus, set[IngestionStatus]] = {
    IngestionStatus.PENDING: {IngestionStatus.UPLOADED, IngestionStatus.FAILED},
    IngestionStatus.UPLOADED: {IngestionStatus.PARSING, IngestionStatus.FAILED},
    IngestionStatus.PARSING: {IngestionStatus.CHUNKING, IngestionStatus.FAILED},
    IngestionStatus.CHUNKING: {IngestionStatus.EMBEDDING, IngestionStatus.FAILED},
    IngestionStatus.EMBEDDING: {IngestionStatus.READY, IngestionStatus.FAILED},
    IngestionStatus.READY: set(),
    IngestionStatus.FAILED: {IngestionStatus.UPLOADED},  # retry re-enters pipeline
}


@dataclass
class Document:
    tenant_id: TenantId
    filename: str
    content_type: str
    size_bytes: int
    storage_key: str  # object-storage key (R2) or local path
    checksum: str
    id: DocumentId = field(default_factory=lambda: DocumentId(new_id()))
    status: IngestionStatus = IngestionStatus.PENDING
    chunk_count: int = 0
    error: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def transition_to(self, target: IngestionStatus) -> None:
        if target not in _TRANSITIONS[self.status]:
            raise InvalidStateError(
                f"Cannot move document {self.id} from {self.status} to {target}"
            )
        self.status = target
        self.updated_at = datetime.now(UTC)
        if target != IngestionStatus.FAILED:
            self.error = None

    def mark_failed(self, reason: str) -> None:
        self.status = IngestionStatus.FAILED
        self.error = reason
        self.updated_at = datetime.now(UTC)

    def mark_ready(self, chunk_count: int) -> None:
        self.transition_to(IngestionStatus.READY)
        self.chunk_count = chunk_count

    @property
    def is_terminal(self) -> bool:
        return self.status in (IngestionStatus.READY, IngestionStatus.FAILED)


@dataclass
class Chunk:
    """A retrievable slice of a document. The embedding vector lives alongside
    this row in pgvector; we keep the text + ordinal for citation."""

    tenant_id: TenantId
    document_id: DocumentId
    ordinal: int
    text: str
    token_estimate: int
    id: str = field(default_factory=lambda: str(new_id()))
