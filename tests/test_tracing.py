"""Tracing tests — NoOp safety, composite fan-out, and agent instrumentation.

No Langfuse/OTel SDK required: a `RecordingTracer` implements the port and
captures what the agent emits, so we assert the *instrumentation* (spans,
generations, scores) without any backend.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import pytest
from src.application.agent.loop import AgentLoop
from src.application.agent.registry import ToolRegistry
from src.application.agent.router import ModelRouter
from src.application.agent.tools import ToolContext, ToolResult, ToolSpec
from src.application.ports.observability import NoOpTracer, Span
from src.infrastructure.observability.tracing import CompositeTracer

# Reuse the fakes from the agent loop tests.
from tests.test_agent_loop import FakeLLM, SearchToolStub


class RecordingSpan:
    def __init__(self, tracer: RecordingTracer, name: str) -> None:
        self._tracer = tracer
        self.name = name
        self.attrs: dict[str, Any] = {}

    def set_attributes(self, **attrs: Any) -> None:
        self.attrs.update(attrs)

    def record_generation(self, **kw: Any) -> None:
        self._tracer.generations.append(kw)

    def score(self, name: str, value: float, *, comment: str | None = None) -> None:
        self._tracer.scores.append((name, value))

    def record_exception(self, exc: BaseException) -> None:
        self._tracer.exceptions.append(exc)


class RecordingTracer:
    def __init__(self) -> None:
        self.span_names: list[str] = []
        self.generations: list[dict] = []
        self.scores: list[tuple[str, float]] = []
        self.exceptions: list[BaseException] = []
        self.flushed = False

    @asynccontextmanager
    async def span(self, name: str, **attrs: Any) -> AsyncIterator[Span]:
        self.span_names.append(name)
        yield RecordingSpan(self, name)

    async def flush(self) -> None:
        self.flushed = True


def _ctx() -> ToolContext:
    return ToolContext(tenant_id=uuid.uuid4())  # type: ignore[arg-type]


def _loop(llm: FakeLLM, tool, tracer) -> AgentLoop:
    return AgentLoop(
        ToolRegistry([tool]),
        ModelRouter(cheap=llm),
        refusal_answer="REFUSE",
        max_steps=4,
        tracer=tracer,
    )


@pytest.mark.asyncio
async def test_noop_tracer_is_safe_and_transparent() -> None:
    tool = SearchToolStub(ToolResult(observation="ctx", data={}))
    llm = FakeLLM(
        [
            '{"action": "search_documents", "action_input": {"query": "x"}}',
            '{"action": "final", "action_input": {"answer": "ok"}}',
        ]
    )
    # With the default NoOp tracer the loop still produces the right answer.
    result = await _loop(llm, tool, NoOpTracer()).run(_ctx(), "q?")
    assert result.answer == "ok"


@pytest.mark.asyncio
async def test_agent_loop_emits_spans_generations_and_scores() -> None:
    tracer = RecordingTracer()
    citations = [{"chunk_id": "c1", "score": 0.91}, {"chunk_id": "c2", "score": 0.4}]
    tool = SearchToolStub(ToolResult(observation="found", data={"citations": citations}))
    llm = FakeLLM(
        [
            '{"action": "search_documents", "action_input": {"query": "refund"}}',
            '{"action": "final", "action_input": {"answer": "30 days"}}',
        ]
    )
    result = await _loop(llm, tool, tracer).run(_ctx(), "refund?")

    assert result.answer == "30 days"
    # One root, two steps, one tool span.
    assert tracer.span_names.count("agent.run") == 1
    assert tracer.span_names.count("agent.step") == 2
    assert tracer.span_names.count("tool.search_documents") == 1
    # A generation recorded per planner call.
    assert len(tracer.generations) == 2
    assert tracer.generations[0]["provider"] == "fake"
    # Retrieval strength surfaced as the top score (0.91, not 0.4).
    assert ("top_retrieval_score", 0.91) in tracer.scores


@pytest.mark.asyncio
async def test_tool_exception_is_recorded_on_span() -> None:
    tracer = RecordingTracer()

    class Boom:
        spec = ToolSpec(name="search_documents", description="x")

        async def run(self, ctx, **kwargs):
            raise RuntimeError("db down")

    llm = FakeLLM(
        [
            '{"action": "search_documents", "action_input": {}}',
            '{"action": "final", "action_input": {"answer": "handled"}}',
        ]
    )
    await _loop(llm, Boom(), tracer).run(_ctx(), "q?")
    assert any(isinstance(e, RuntimeError) for e in tracer.exceptions)


@pytest.mark.asyncio
async def test_composite_tracer_fans_out_to_all_backends() -> None:
    a, b = RecordingTracer(), RecordingTracer()
    composite = CompositeTracer([a, b])

    async with composite.span("root", k="v") as span:
        span.record_generation(model="m", provider="p", prompt="in", completion="out", tokens=5)
        span.score("faithfulness", 0.8)

    for t in (a, b):
        assert t.span_names == ["root"]
        assert t.generations[0]["tokens"] == 5
        assert ("faithfulness", 0.8) in t.scores

    await composite.flush()
    assert a.flushed and b.flushed
