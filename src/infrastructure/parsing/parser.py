"""Document text extraction by content type.

Runs CPU-bound parsing in a thread so it doesn't block the event loop. Supports
PDF, DOCX, Markdown, and plain text — the formats that cover the vast majority
of knowledge-base uploads.
"""

from __future__ import annotations

import asyncio
import io

from src.domain.shared.errors import InvalidStateError


class MultiFormatParser:
    def supports(self, content_type: str, filename: str) -> bool:
        return self._kind(content_type, filename) is not None

    async def extract_text(self, data: bytes, content_type: str, filename: str) -> str:
        kind = self._kind(content_type, filename)
        if kind is None:
            raise InvalidStateError(f"Unsupported file type: {content_type} ({filename})")
        return await asyncio.to_thread(self._extract_sync, data, kind)

    def _kind(self, content_type: str, filename: str) -> str | None:
        name = filename.lower()
        if "pdf" in content_type or name.endswith(".pdf"):
            return "pdf"
        if "wordprocessingml" in content_type or name.endswith(".docx"):
            return "docx"
        if name.endswith((".md", ".markdown")) or "markdown" in content_type:
            return "markdown"
        if content_type.startswith("text/") or name.endswith((".txt", ".text")):
            return "text"
        return None

    def _extract_sync(self, data: bytes, kind: str) -> str:
        if kind == "pdf":
            from pypdf import PdfReader

            reader = PdfReader(io.BytesIO(data))
            return "\n\n".join((page.extract_text() or "") for page in reader.pages)
        if kind == "docx":
            import docx

            doc = docx.Document(io.BytesIO(data))
            return "\n".join(p.text for p in doc.paragraphs)
        # markdown / text: decode as-is (markdown structure is fine for retrieval)
        return data.decode("utf-8", errors="replace")
