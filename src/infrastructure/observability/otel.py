"""OpenTelemetry tracer adapter.

Maps our `Span` port onto OTel spans. Nesting is automatic: OTel's
`start_as_current_span` makes a span the current context, so any span opened
inside an `async with tracer.span(...)` block becomes its child. LLM-specific
data (model, tokens) is recorded with the `gen_ai.*` semantic-convention
attributes so traces are portable to any OTel backend (Jaeger, Tempo, etc.).

Imports are lazy and every SDK call is best-effort: a telemetry failure must
never propagate into the traced request.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import structlog

from src.application.ports.observability import Span

log = structlog.get_logger(__name__)


def _coerce(value: Any) -> Any:
    """OTel attributes accept only str/bool/int/float (and sequences). Stringify
    anything else so a rich attr never gets silently dropped."""
    if isinstance(value, (str, bool, int, float)):
        return value
    return str(value)


class _OTelSpan:
    def __init__(self, span: Any, status_error: Any) -> None:
        self._span = span
        self._status_error = status_error  # opentelemetry.trace.Status(ERROR)

    def set_attributes(self, **attrs: Any) -> None:
        try:
            for key, value in attrs.items():
                self._span.set_attribute(key, _coerce(value))
        except Exception:  # noqa: BLE001 - never break the caller
            pass

    def record_generation(
        self, *, model: str, provider: str | None, prompt: str, completion: str, tokens: int
    ) -> None:
        self.set_attributes(
            **{
                "gen_ai.request.model": model,
                "gen_ai.system": provider or "unknown",
                "gen_ai.usage.total_tokens": tokens,
                "gen_ai.prompt": prompt[:2000],
                "gen_ai.completion": completion[:2000],
            }
        )

    def score(self, name: str, value: float, *, comment: str | None = None) -> None:
        self.set_attributes(**{f"score.{name}": value})
        if comment:
            self.set_attributes(**{f"score.{name}.comment": comment})

    def record_exception(self, exc: BaseException) -> None:
        try:
            self._span.record_exception(exc)
            if self._status_error is not None:
                self._span.set_status(self._status_error)
        except Exception:  # noqa: BLE001
            pass


class OTelTracer:
    def __init__(self, service_name: str = "rag-platform") -> None:
        from opentelemetry import trace
        from opentelemetry.trace import Status, StatusCode

        self._trace = trace
        self._tracer = trace.get_tracer(service_name)
        self._status_error = Status(StatusCode.ERROR)

    @asynccontextmanager
    async def span(self, name: str, **attrs: Any) -> AsyncIterator[Span]:
        with self._tracer.start_as_current_span(name) as otel_span:
            span = _OTelSpan(otel_span, self._status_error)
            span.set_attributes(**attrs)
            try:
                yield span
            except Exception as exc:  # noqa: BLE001 - record then re-raise
                span.record_exception(exc)
                raise

    async def flush(self) -> None:
        # The configured SpanProcessor flushes on shutdown; nothing to do here.
        return None
