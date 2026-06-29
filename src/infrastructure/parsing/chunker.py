"""Recursive, overlap-aware text chunker.

Splits on the largest natural boundary that fits (paragraphs → lines →
sentences → words), targeting a character budget with overlap so context isn't
lost across chunk edges. Character-based to avoid a tokenizer dependency on the
free tier; ~4 chars ≈ 1 token is a good enough heuristic.
"""

from __future__ import annotations

import re

_SEPARATORS = ["\n\n", "\n", ". ", " "]


class RecursiveChunker:
    def __init__(self, target_chars: int = 1200, overlap_chars: int = 150) -> None:
        self._target = target_chars
        self._overlap = overlap_chars

    def chunk(self, text: str) -> list[str]:
        text = re.sub(r"[ \t]+", " ", text).strip()
        if not text:
            return []
        pieces = self._split(text, 0)
        return self._merge_with_overlap(pieces)

    def _split(self, text: str, sep_idx: int) -> list[str]:
        if len(text) <= self._target or sep_idx >= len(_SEPARATORS):
            return [text]
        sep = _SEPARATORS[sep_idx]
        parts = text.split(sep)
        out: list[str] = []
        for part in parts:
            piece = part + sep
            if len(piece) > self._target:
                out.extend(self._split(piece, sep_idx + 1))
            else:
                out.append(piece)
        return out

    def _merge_with_overlap(self, pieces: list[str]) -> list[str]:
        chunks: list[str] = []
        buf = ""
        for piece in pieces:
            if len(buf) + len(piece) <= self._target:
                buf += piece
            else:
                if buf.strip():
                    chunks.append(buf.strip())
                tail = buf[-self._overlap :] if self._overlap else ""
                buf = tail + piece
        if buf.strip():
            chunks.append(buf.strip())
        return chunks
