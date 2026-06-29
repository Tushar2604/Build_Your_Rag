"""Domain unit tests — no database, no frameworks."""

from __future__ import annotations

import pytest
from src.domain.document.entities import Document, IngestionStatus
from src.domain.shared.errors import InvalidStateError
from src.domain.shared.identifiers import TenantId, new_id


def _doc() -> Document:
    return Document(
        tenant_id=TenantId(new_id()),
        filename="a.pdf",
        content_type="application/pdf",
        size_bytes=10,
        storage_key="k",
        checksum="c",
    )


def test_happy_path_transitions() -> None:
    doc = _doc()
    doc.transition_to(IngestionStatus.UPLOADED)
    doc.transition_to(IngestionStatus.PARSING)
    doc.transition_to(IngestionStatus.CHUNKING)
    doc.transition_to(IngestionStatus.EMBEDDING)
    doc.mark_ready(chunk_count=5)
    assert doc.status is IngestionStatus.READY
    assert doc.chunk_count == 5
    assert doc.is_terminal


def test_illegal_transition_raises() -> None:
    doc = _doc()  # PENDING
    with pytest.raises(InvalidStateError):
        doc.transition_to(IngestionStatus.READY)


def test_failed_can_be_retried() -> None:
    doc = _doc()
    doc.mark_failed("boom")
    assert doc.status is IngestionStatus.FAILED
    assert doc.error == "boom"
    # Retry re-enters the pipeline.
    doc.transition_to(IngestionStatus.UPLOADED)
    assert doc.status is IngestionStatus.UPLOADED
    assert doc.error is None
