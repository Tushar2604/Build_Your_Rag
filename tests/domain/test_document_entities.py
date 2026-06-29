"""Unit tests for the document aggregate.

The happy-path / illegal / retry transitions are covered in
`tests/test_document_state_machine.py`; this file completes coverage of every
transition edge, the `mark_*` helpers, `is_terminal`, and the `Chunk` entity.
"""

from __future__ import annotations

import uuid
from datetime import datetime

import pytest
from src.domain.document.entities import (
    _TRANSITIONS,
    Chunk,
    Document,
    IngestionStatus,
)
from src.domain.shared.errors import InvalidStateError
from src.domain.shared.identifiers import DocumentId, TenantId, new_id


def _doc(status: IngestionStatus = IngestionStatus.PENDING) -> Document:
    d = Document(
        tenant_id=TenantId(new_id()),
        filename="a.pdf",
        content_type="application/pdf",
        size_bytes=10,
        storage_key="k",
        checksum="c",
    )
    d.status = status
    return d


# --- status enum / transition table ---
def test_status_values() -> None:
    assert IngestionStatus.PENDING == "pending"
    assert IngestionStatus.READY == "ready"
    assert IngestionStatus.FAILED == "failed"


def test_transition_table_covers_every_status() -> None:
    assert set(_TRANSITIONS) == set(IngestionStatus)


# --- transition_to: every allowed edge ---
@pytest.mark.parametrize(
    ("frm", "to"),
    [
        (IngestionStatus.PENDING, IngestionStatus.UPLOADED),
        (IngestionStatus.PENDING, IngestionStatus.FAILED),
        (IngestionStatus.UPLOADED, IngestionStatus.PARSING),
        (IngestionStatus.UPLOADED, IngestionStatus.FAILED),
        (IngestionStatus.PARSING, IngestionStatus.CHUNKING),
        (IngestionStatus.PARSING, IngestionStatus.FAILED),
        (IngestionStatus.CHUNKING, IngestionStatus.EMBEDDING),
        (IngestionStatus.CHUNKING, IngestionStatus.FAILED),
        (IngestionStatus.EMBEDDING, IngestionStatus.READY),
        (IngestionStatus.EMBEDDING, IngestionStatus.FAILED),
        (IngestionStatus.FAILED, IngestionStatus.UPLOADED),
    ],
)
def test_allowed_transitions(frm: IngestionStatus, to: IngestionStatus) -> None:
    doc = _doc(frm)
    doc.transition_to(to)
    assert doc.status is to


def test_ready_is_terminal_no_transitions() -> None:
    assert _TRANSITIONS[IngestionStatus.READY] == set()
    doc = _doc(IngestionStatus.READY)
    with pytest.raises(InvalidStateError):
        doc.transition_to(IngestionStatus.UPLOADED)


def test_failed_only_goes_to_uploaded() -> None:
    doc = _doc(IngestionStatus.FAILED)
    with pytest.raises(InvalidStateError):
        doc.transition_to(IngestionStatus.PARSING)


def test_transition_to_clears_error_on_non_failed() -> None:
    doc = _doc(IngestionStatus.FAILED)
    doc.error = "previous failure"
    doc.transition_to(IngestionStatus.UPLOADED)
    assert doc.error is None


def test_transition_updates_timestamp() -> None:
    doc = _doc(IngestionStatus.PENDING)
    before = doc.updated_at
    doc.transition_to(IngestionStatus.UPLOADED)
    assert doc.updated_at >= before
    assert isinstance(doc.updated_at, datetime)


def test_illegal_transition_message_mentions_states() -> None:
    doc = _doc(IngestionStatus.PENDING)
    with pytest.raises(InvalidStateError) as ei:
        doc.transition_to(IngestionStatus.READY)
    assert "pending" in str(ei.value)
    assert "ready" in str(ei.value)


# --- mark_failed ---
def test_mark_failed_from_any_state() -> None:
    doc = _doc(IngestionStatus.PARSING)
    doc.mark_failed("corrupt file")
    assert doc.status is IngestionStatus.FAILED
    assert doc.error == "corrupt file"


def test_mark_failed_does_not_validate_transition() -> None:
    # mark_failed bypasses the transition table (READY has no outgoing edges).
    doc = _doc(IngestionStatus.READY)
    doc.mark_failed("late failure")
    assert doc.status is IngestionStatus.FAILED


# --- mark_ready ---
def test_mark_ready_sets_count_and_status() -> None:
    doc = _doc(IngestionStatus.EMBEDDING)
    doc.mark_ready(chunk_count=7)
    assert doc.status is IngestionStatus.READY
    assert doc.chunk_count == 7


def test_mark_ready_requires_embedding_state() -> None:
    doc = _doc(IngestionStatus.PENDING)
    with pytest.raises(InvalidStateError):
        doc.mark_ready(chunk_count=1)


# --- is_terminal ---
@pytest.mark.parametrize(
    ("status", "terminal"),
    [
        (IngestionStatus.PENDING, False),
        (IngestionStatus.UPLOADED, False),
        (IngestionStatus.PARSING, False),
        (IngestionStatus.CHUNKING, False),
        (IngestionStatus.EMBEDDING, False),
        (IngestionStatus.READY, True),
        (IngestionStatus.FAILED, True),
    ],
)
def test_is_terminal(status: IngestionStatus, terminal: bool) -> None:
    assert _doc(status).is_terminal is terminal


def test_document_defaults() -> None:
    doc = _doc()
    assert doc.status is IngestionStatus.PENDING
    assert doc.chunk_count == 0
    assert doc.error is None
    assert isinstance(doc.id, uuid.UUID)


# --- Chunk ---
def test_chunk_defaults_and_id_is_uuid_string() -> None:
    c = Chunk(
        tenant_id=TenantId(new_id()),
        document_id=DocumentId(new_id()),
        ordinal=0,
        text="hello",
        token_estimate=2,
    )
    assert isinstance(c.id, str)
    # id is a stringified uuid4
    assert uuid.UUID(c.id).version == 4


def test_chunk_ids_unique() -> None:
    args = {
        "tenant_id": TenantId(new_id()),
        "document_id": DocumentId(new_id()),
        "ordinal": 0,
        "text": "x",
        "token_estimate": 1,
    }
    assert Chunk(**args).id != Chunk(**args).id
