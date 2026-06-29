"""Tracer composition + the build-from-settings factory.

`build_tracer` inspects config and returns whatever is wired:
  * nothing configured        -> `NoOpTracer` (zero overhead, the default)
  * one backend configured    -> that backend's tracer
  * both configured           -> a `CompositeTracer` fanning every span out to both

A `CompositeTracer` opens one child span per backend for each logical span and
forwards every record/score call to all of them, so an answer can be traced to
Langfuse (for the LLM-quality view) and OpenTelemetry (for system-level latency)
at the same time.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import AsyncExitStack, asynccontextmanager
from typing import Any

import structlog

from src.application.ports.observability import NoOpTracer, Span, Tracer
from src.config import Settings

log = structlog.get_logger(__name__)


class _CompositeSpan:
    """Forwards every call to each backend's span."""

    def __init__(self, spans: list[Span]) -> None:
        self._spans = spans

    def set_attributes(self, **attrs: Any) -> None:
        for s in self._spans:
            s.set_attributes(**attrs)

    def record_generation(
        self, *, model: str, provider: str | None, prompt: str, completion: str, tokens: int
    ) -> None:
        for s in self._spans:
            s.record_generation(
                model=model, provider=provider, prompt=prompt, completion=completion, tokens=tokens
            )

    def score(self, name: str, value: float, *, comment: str | None = None) -> None:
        for s in self._spans:
            s.score(name, value, comment=comment)

    def record_exception(self, exc: BaseException) -> None:
        for s in self._spans:
            s.record_exception(exc)


class CompositeTracer:
    def __init__(self, tracers: list[Tracer]) -> None:
        self._tracers = tracers

    @asynccontextmanager
    async def span(self, name: str, **attrs: Any) -> AsyncIterator[Span]:
        async with AsyncExitStack() as stack:
            spans = [
                await stack.enter_async_context(t.span(name, **attrs)) for t in self._tracers
            ]
            yield _CompositeSpan(spans)

    async def flush(self) -> None:
        for t in self._tracers:
            await t.flush()


def build_tracer(settings: Settings) -> Tracer:
    """Assemble the tracer for this process from config. Any backend that fails to
    initialise (missing dependency, bad config) is skipped with a warning rather
    than blocking startup — observability is never load-bearing."""
    tracers: list[Tracer] = []

    if settings.langfuse_enabled:
        try:
            from src.infrastructure.observability.langfuse_tracer import LangfuseTracer

            tracers.append(
                LangfuseTracer(
                    public_key=settings.langfuse_public_key,
                    secret_key=settings.langfuse_secret_key,
                    host=settings.langfuse_host,
                )
            )
            log.info("tracing.langfuse_enabled", host=settings.langfuse_host or "cloud")
        except Exception:  # noqa: BLE001
            log.exception("tracing.langfuse_init_failed")

    if settings.otel_enabled:
        try:
            from src.infrastructure.observability.otel import OTelTracer

            tracers.append(OTelTracer(service_name=settings.otel_service_name))
            log.info("tracing.otel_enabled", service=settings.otel_service_name)
        except Exception:  # noqa: BLE001
            log.exception("tracing.otel_init_failed")

    if not tracers:
        return NoOpTracer()
    if len(tracers) == 1:
        return tracers[0]
    return CompositeTracer(tracers)
