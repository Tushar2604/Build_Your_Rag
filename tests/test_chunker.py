from __future__ import annotations

from src.infrastructure.parsing.chunker import RecursiveChunker


def test_empty_text_yields_no_chunks() -> None:
    assert RecursiveChunker().chunk("   ") == []


def test_short_text_is_single_chunk() -> None:
    chunks = RecursiveChunker().chunk("Hello world.")
    assert chunks == ["Hello world."]


def test_long_text_splits_with_overlap() -> None:
    text = " ".join(f"sentence number {i}." for i in range(400))
    chunks = RecursiveChunker(target_chars=300, overlap_chars=50).chunk(text)
    assert len(chunks) > 1
    assert all(len(c) <= 400 for c in chunks)  # target + overlap headroom
