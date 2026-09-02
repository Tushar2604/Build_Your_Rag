"""Agent loop tests with a fake LLM + fake tool — no network, no DB.

These pin the loop's contract and its handling of real agent failure modes:
malformed actions, hallucinated tool names, tool errors, and step exhaustion.
"""

from __future__ import annotations

import uuid

import pytest
from src.application.agent.loop import AgentLoop, _parse_action
from src.application.agent.registry import ToolRegistry
from src.application.agent.router import ModelRouter
from src.application.agent.tools import ToolContext, ToolResult, ToolSpec
from src.application.ports.services import LLMResult


class FakeLLM:
    """Returns scripted responses in order; records every prompt it received."""

    name = "fake"

    def __init__(self, scripted: list[str]) -> None:
        self._scripted = list(scripted)
        self.calls: list[tuple[str, str]] = []

    _DEFAULT = '{"action": "final", "action_input": {"answer": "done"}}'

    async def generate(self, system: str, user: str) -> LLMResult:
        self.calls.append((system, user))
        text = self._scripted.pop(0) if self._scripted else self._DEFAULT
        return LLMResult(text=text, tokens_used=7, provider=self.name, model="fake-1")

    async def stream(self, system, user, on_provider=None):  # pragma: no cover - unused
        yield ""


class SearchToolStub:
    spec = ToolSpec(name="search_documents", description="search", parameters={"query": {}})

    def __init__(self, result: ToolResult) -> None:
        self._result = result
        self.calls: list[dict] = []

    async def run(self, ctx: ToolContext, **kwargs) -> ToolResult:
        self.calls.append(kwargs)
        return self._result


def _ctx() -> ToolContext:
    return ToolContext(tenant_id=uuid.uuid4())  # type: ignore[arg-type]


def _loop(llm: FakeLLM, tool, *, max_steps: int = 6) -> AgentLoop:
    registry = ToolRegistry([tool])
    return AgentLoop(registry, ModelRouter(cheap=llm), refusal_answer="REFUSE", max_steps=max_steps)


@pytest.mark.asyncio
async def test_happy_path_search_then_final() -> None:
    citation = {"chunk_id": "c1", "document_id": "d1", "ordinal": 0, "score": 0.9}
    tool = SearchToolStub(
        ToolResult(
            observation="[doc=d1 score=0.9]\nRefunds within 30 days.",
            data={"citations": [citation]},
        )
    )
    search = (
        '{"thought": "look it up", "action": "search_documents", '
        '"action_input": {"query": "refund"}}'
    )
    final = '{"thought": "found it", "action": "final", "action_input": {"answer": "30 days."}}'
    llm = FakeLLM([search, final])
    result = await _loop(llm, tool).run(_ctx(), "refund window?")

    assert result.answer == "30 days."
    assert result.trace.stop_reason == "final"
    assert result.trace.tools_used() == ["search_documents"]
    assert tool.calls == [{"query": "refund"}]
    # Tokens accumulate across both planner calls.
    assert result.trace.tokens_used == 14
    # The tool's structured citations survive on the step for the use case.
    assert result.trace.steps[0].data["citations"][0]["chunk_id"] == "c1"


@pytest.mark.asyncio
async def test_malformed_action_is_recoverable() -> None:
    tool = SearchToolStub(ToolResult(observation="ok"))
    llm = FakeLLM(
        [
            "I think I should search but here is no json",
            '{"action": "final", "action_input": {"answer": "recovered"}}',
        ]
    )
    result = await _loop(llm, tool).run(_ctx(), "q?")
    assert result.answer == "recovered"
    # The malformed turn was recorded but did not crash the run.
    assert result.trace.num_steps == 2
    assert "not a single valid JSON action" in result.trace.steps[0].observation


@pytest.mark.asyncio
async def test_unknown_tool_is_reported_back() -> None:
    tool = SearchToolStub(ToolResult(observation="ok"))
    llm = FakeLLM(
        [
            '{"action": "do_magic", "action_input": {}}',
            '{"action": "final", "action_input": {"answer": "ok"}}',
        ]
    )
    result = await _loop(llm, tool).run(_ctx(), "q?")
    assert "Unknown tool" in result.trace.steps[0].observation
    assert result.answer == "ok"


@pytest.mark.asyncio
async def test_tool_error_becomes_observation_not_crash() -> None:
    class Boom:
        spec = ToolSpec(name="search_documents", description="x")

        async def run(self, ctx, **kwargs):
            raise RuntimeError("db down")

    llm = FakeLLM(
        [
            '{"action": "search_documents", "action_input": {"query": "x"}}',
            '{"action": "final", "action_input": {"answer": "handled"}}',
        ]
    )
    result = await _loop(llm, Boom()).run(_ctx(), "q?")
    assert "raised an error: db down" in result.trace.steps[0].observation
    assert result.answer == "handled"


@pytest.mark.asyncio
async def test_step_budget_exhaustion_forces_close_out() -> None:
    tool = SearchToolStub(ToolResult(observation="some context"))
    # Always searches, never finalises -> hits the budget.
    never_final = '{"action": "search_documents", "action_input": {"query": "x"}}'
    # Exactly max_steps planner turns, then one close-out call.
    llm = FakeLLM([never_final] * 3 + ["best effort answer"])
    result = await _loop(llm, tool, max_steps=3).run(_ctx(), "q?")
    assert result.trace.stop_reason == "max_steps"
    assert result.trace.num_steps == 3
    assert result.answer == "best effort answer"


def test_parse_action_strips_markdown_fence() -> None:
    text = '```json\n{"action": "final", "action_input": {"answer": "hi"}}\n```'
    thought, action, action_input, error = _parse_action(text)
    assert error is None
    assert action == "final"
    assert action_input == {"answer": "hi"}


def test_parse_action_reports_missing_action() -> None:
    _, _, _, error = _parse_action('{"thought": "no action here"}')
    assert error == "missing 'action' field"


class TestBusinessContextReachesTheModel:
    """The bug behind "the assistant ignores everything I configured": the
    loop used to build its system prompt from nothing but its own fixed
    tool-use rules, on every channel that runs through it. A tenant's own
    Identity/Facts/Flow content — however carefully written in the builder —
    was never in the prompt at all. `tenant_prompt` is how it gets there.
    """

    async def test_the_tenants_own_prompt_is_sent_to_the_model(self) -> None:
        tool = SearchToolStub(ToolResult(observation="found it"))
        llm = FakeLLM(['{"action": "final", "action_input": {"answer": "done"}}'])
        loop = _loop(llm, tool)

        await loop.run(
            _ctx(),
            "who are you?",
            tenant_prompt="You are Maya, the receptionist for Bright Smile Dental.",
        )

        system_seen = llm.calls[0][0]
        assert "Bright Smile Dental" in system_seen
        assert "Maya" in system_seen

    async def test_an_empty_tenant_prompt_does_not_crash_and_says_so_honestly(
        self,
    ) -> None:
        tool = SearchToolStub(ToolResult(observation="x"))
        llm = FakeLLM(['{"action": "final", "action_input": {"answer": "done"}}'])
        loop = _loop(llm, tool)

        await loop.run(_ctx(), "hello", tenant_prompt="")

        system_seen = llm.calls[0][0]
        assert "No business details are configured" in system_seen

    async def test_tenant_content_with_literal_braces_does_not_break_formatting(
        self,
    ) -> None:
        # The regression this guards: `tenant_prompt` is free text an operator
        # typed in a browser. Threading it through `str.format()` — the same
        # mechanism that fills {catalog}/{refusal}/{today} — would raise on a
        # stray brace in the tenant's own words. It must reach the model
        # completely intact instead.
        tool = SearchToolStub(ToolResult(observation="x"))
        llm = FakeLLM(['{"action": "final", "action_input": {"answer": "done"}}'])
        loop = _loop(llm, tool)
        tricky = 'Reply in this exact JSON shape: {"greeting": "hi"} and never {improvise}.'

        await loop.run(_ctx(), "hello", tenant_prompt=tricky)

        assert tricky in llm.calls[0][0]

    async def test_the_default_system_template_still_has_no_business_section_gap(
        self,
    ) -> None:
        # A caller that never passes tenant_prompt at all (the pre-existing
        # calling convention) must still render cleanly rather than leaving a
        # literal marker string in the prompt.
        tool = SearchToolStub(ToolResult(observation="x"))
        llm = FakeLLM(['{"action": "final", "action_input": {"answer": "done"}}'])
        loop = _loop(llm, tool)

        await loop.run(_ctx(), "hello")

        system_seen = llm.calls[0][0]
        assert "<<BUSINESS_CONTEXT>>" not in system_seen
        assert "<<IDENTITY_AND_VOICE>>" not in system_seen


class TestIdentityAndPlaceholderGuardrails:
    """Requested directly: a human-sounding answer to "who are you", and no
    literal [bracket] placeholder ever reaching a real customer. Both are
    baked into every prompt this loop renders — not tenant configuration,
    because every assistant on the platform benefits from both."""

    async def test_the_identity_instruction_is_present(self) -> None:
        tool = SearchToolStub(ToolResult(observation="x"))
        llm = FakeLLM(['{"action": "final", "action_input": {"answer": "done"}}'])
        loop = _loop(llm, tool)

        await loop.run(_ctx(), "who are you?")

        system_seen = llm.calls[0][0]
        assert "never say" in system_seen.lower()
        assert "first name" in system_seen.lower()

    async def test_the_no_placeholder_instruction_is_present(self) -> None:
        tool = SearchToolStub(ToolResult(observation="x"))
        llm = FakeLLM(['{"action": "final", "action_input": {"answer": "done"}}'])
        loop = _loop(llm, tool)

        await loop.run(_ctx(), "hi")

        system_seen = llm.calls[0][0]
        assert "NEVER SHOW A PLACEHOLDER" in system_seen
        assert "[user_name]" in system_seen or "[name]" in system_seen
