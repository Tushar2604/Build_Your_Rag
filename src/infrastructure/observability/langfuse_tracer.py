"""Langfuse tracer adapter — LLM-native observability.

Langfuse models a run as a *trace* containing nested *spans* and *generations*,
plus *scores* attached to the trace. That maps directly onto our port:

  * the outermost `span()` opens a Langfuse trace;
  * nested `span()`s become child spans (parent tracked in a contextvar);
  * `record_generation` logs an LLM call with model/tokens/in/out;
  * `score` attaches a numeric eval score (faithfulness, retrieval strength).

This is what lets you open a single answer in the Langfuse UI and see every
retrieval, every model call, the token cost, and the quality scores side by side
— the "review outputs / triage failures" workflow.

Everything is best-effort and lazily imported: if the SDK or keys are missing, or
a call fails, the adapter degrades silently rather than touching the request.
"""

from __future__ import annotations

import contextlib
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any

import structlog

from src.application.ports.observability import Span

log = structlog.get_logger(__name__)

# The current Langfuse observation (trace or span) — the parent for the next
# nested span/generation. Reset on context exit so nesting is exact.
_current: ContextVar[_LfObservation | None] = ContextVar("langfuse_current", default=None)


@dataclass
class _LfObservation:
    handle: Any  # langfuse trace or span object
    trace_id: str | None
    client: Any


class _LangfuseSpan:
    def __init__(self, obs: _LfObservation) -> None:
        self._obs = obs

    def set_attributes(self, **attrs: Any) -> None:
        with contextlib.suppress(Exception):  # noqa: BLE001 - telemetry is best-effort
            self._obs.handle.update(metadata=attrs)

    def record_generation(
        self, *, model: str, provider: str | None, prompt: str, completion: str, tokens: int
    ) -> None:
        try:
            gen = self._obs.handle.generation(
                name="llm-call",
                model=model,
                input=prompt[:4000],
                metadata={"provider": provider},
                usage={"total": tokens, "unit": "TOKENS"},
            )
            gen.end(output=completion[:4000])
        except Exception:  # noqa: BLE001
            pass

    def score(self, name: str, value: float, *, comment: str | None = None) -> None:
        try:
            if self._obs.trace_id is not None:
                self._obs.client.score(
                    trace_id=self._obs.trace_id, name=name, value=value, comment=comment
                )
        except Exception:  # noqa: BLE001
            pass

    def record_exception(self, exc: BaseException) -> None:
        with contextlib.suppress(Exception):  # noqa: BLE001 - telemetry is best-effort
            self._obs.handle.update(level="ERROR", status_message=f"{type(exc).__name__}: {exc}")


class LangfuseTracer:
    def __init__(self, *, public_key: str, secret_key: str, host: str | None = None) -> None:
        from langfuse import Langfuse

        self._client = Langfuse(
            public_key=public_key, secret_key=secret_key, host=host or None
        )

    @asynccontextmanager
    async def span(self, name: str, **attrs: Any) -> AsyncIterator[Span]:
        parent = _current.get()
        obs = self._begin(name, parent, attrs)
        token = _current.set(obs)
        try:
            span = _LangfuseSpan(obs)
            yield span
        except Exception as exc:  # noqa: BLE001
            _LangfuseSpan(obs).record_exception(exc)
            raise
        finally:
            _current.reset(token)
            self._end(obs)

    def _begin(
        self, name: str, parent: _LfObservation | None, attrs: dict[str, Any]
    ) -> _LfObservation:
        try:
            if parent is None:
                handle = self._client.trace(name=name, metadata=attrs)
                trace_id = getattr(handle, "id", None)
                return _LfObservation(handle=handle, trace_id=trace_id, client=self._client)
            handle = parent.handle.span(name=name, metadata=attrs)
            return _LfObservation(handle=handle, trace_id=parent.trace_id, client=self._client)
        except Exception:  # noqa: BLE001 - fall back to a detached no-op observation
            return _LfObservation(handle=_NullHandle(), trace_id=None, client=self._client)

    def _end(self, obs: _LfObservation) -> None:
        try:
            end = getattr(obs.handle, "end", None)
            if callable(end):
                end()
        except Exception:  # noqa: BLE001
            pass

    async def flush(self) -> None:
        with contextlib.suppress(Exception):  # noqa: BLE001 - telemetry is best-effort
            self._client.flush()


class _NullHandle:
    """Stand-in when the SDK errors mid-trace, so span methods stay callable."""

    def update(self, **_: Any) -> None: ...
    def span(self, **_: Any) -> _NullHandle:
        return self

    def generation(self, **_: Any) -> _NullHandle:
        return self

    def end(self, **_: Any) -> None: ...
