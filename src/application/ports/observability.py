"""Tracing ports — the seam between the core and AI-observability backends.

The application emits *what happened* (spans, LLM generations, eval scores)
through these Protocols; infrastructure decides *where it goes* (Langfuse,
OpenTelemetry, both, or nowhere). Same hexagonal direction as every other port,
and the default is a no-op so the platform runs with zero observability config —
free-tier friendly, like the rest of the stack.

The `Span` surface is deliberately shaped to satisfy both worlds:
  * `set_attributes` / `record_exception` map cleanly to OpenTelemetry spans.
  * `record_generation` / `score` map to Langfuse generations and scores — the
    LLM-specific concepts (model, tokens, faithfulness score) OTel has no native
    notion of.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class Span(Protocol):
    """A single unit of traced work. Never raises into the caller — observability
    must not be able to break the request it is observing."""

    def set_attributes(self, **attrs: Any) -> None: ...

    def record_generation(
        self,
        *,
        model: str,
        provider: str | None,
        prompt: str,
        completion: str,
        tokens: int,
    ) -> None:
        """Record an LLM call within this span (Langfuse 'generation')."""
        ...

    def score(self, name: str, value: float, *, comment: str | None = None) -> None:
        """Attach a numeric quality score (e.g. faithfulness, max retrieval score)."""
        ...

    def record_exception(self, exc: BaseException) -> None: ...


@runtime_checkable
class Tracer(Protocol):
    def span(self, name: str, **attrs: Any) -> AbstractAsyncSpanCtx: ...

    async def flush(self) -> None:
        """Force-export buffered telemetry (call on shutdown / after a CLI run)."""
        ...


# Alias for readability in signatures; the concrete return is an async context
# manager yielding a Span.
AbstractAsyncSpanCtx = AsyncIterator[Span]


class NoOpSpan:
    """A span that records nothing. The zero-config default."""

    def set_attributes(self, **attrs: Any) -> None:
        return None

    def record_generation(
        self, *, model: str, provider: str | None, prompt: str, completion: str, tokens: int
    ) -> None:
        return None

    def score(self, name: str, value: float, *, comment: str | None = None) -> None:
        return None

    def record_exception(self, exc: BaseException) -> None:
        return None


class NoOpTracer:
    """Default tracer: every span is a no-op. Used when no backend is configured."""

    @asynccontextmanager
    async def span(self, name: str, **attrs: Any) -> AsyncIterator[Span]:
        yield NoOpSpan()

    async def flush(self) -> None:
        return None
