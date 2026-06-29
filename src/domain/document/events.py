from __future__ import annotations

from dataclasses import dataclass

from src.domain.shared.events import DomainEvent
from src.domain.shared.identifiers import DocumentId


@dataclass(frozen=True, kw_only=True)
class DocumentUploaded(DomainEvent):
    document_id: DocumentId
    filename: str


@dataclass(frozen=True, kw_only=True)
class DocumentIngested(DomainEvent):
    document_id: DocumentId
    chunk_count: int


@dataclass(frozen=True, kw_only=True)
class DocumentIngestionFailed(DomainEvent):
    document_id: DocumentId
    reason: str
