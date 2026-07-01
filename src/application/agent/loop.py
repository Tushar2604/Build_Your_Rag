"""A provider-agnostic ReAct agent loop.

The loop drives a think→act→observe cycle on top of the plain
`LLMProvider.generate` port (no native tool-calling API required, so it runs over
Groq *and* Gemini and through the existing failover router). Each turn the
planner emits a JSON action; the loop executes the named tool, feeds the
observation back, and repeats until the planner emits a `final` action or the
step budget is exhausted.

Design choices that reflect real agent failure modes:

  * Hard `max_steps` budget — an agent that won't converge must terminate with a
    best-effort answer, never loop forever or burn the token quota.
  * Defensive action parsing — models wrap JSON in prose or markdown fences and
    occasionally hallucinate a tool name. Both are handled as recoverable
    observations the planner can correct on the next turn, not crashes.
  * Every step is recorded in an `AgentTrace` for observability and eval.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

import structlog

from src.application.agent.registry import ToolRegistry
from src.application.agent.router import ModelRouter
from src.application.agent.tools import ToolContext
from src.application.agent.trace import AgentStep, AgentTrace
from src.application.ports.observability import NoOpTracer, Tracer

log = structlog.get_logger(__name__)

_JSON_OBJECT = re.compile(r"\{.*\}", re.DOTALL)

_SYSTEM_TEMPLATE = """You are a warm, friendly, and genuinely helpful assistant \
answering questions about a specific set of documents. You must ground every \
answer in tool results — never answer from your own prior knowledge.

You have these tools:
{catalog}

Work in steps. On each step respond with ONE JSON object and nothing else:
  To use a tool:   {{"thought": "...", "action": "<tool_name>", "action_input": {{...}}}}
  To finish:       {{"thought": "...", "action": "final", "action_input": {{"answer": "..."}}}}

Rules:
- Always search the documents before answering a factual question.
- If the tools return no relevant information, finish with this exact answer:
  "{refusal}"
- Do not invent tool names. Use only the tools listed above.
- Keep going until you can answer, then use "final".
- Write the final "answer" in a warm, human, humble voice: you may acknowledge a
  good question, and close by briefly inviting a follow-up (e.g. ask what else
  they'd like to know). Keep it natural and grounded in the tool results.
"""


@dataclass
class AgentResult:
    answer: str
    trace: AgentTrace


class AgentLoop:
    def __init__(
        self,
        registry: ToolRegistry,
        router: ModelRouter,
        *,
        refusal_answer: str,
        max_steps: int = 6,
        tracer: Tracer | None = None,
    ) -> None:
        self._registry = registry
        self._router = router
        self._refusal = refusal_answer
        self._max_steps = max_steps
        self._tracer = tracer or NoOpTracer()

    def _system_prompt(self) -> str:
        return _SYSTEM_TEMPLATE.format(
            catalog=self._registry.render_catalog(), refusal=self._refusal
        )

    async def run(self, ctx: ToolContext, question: str) -> AgentResult:
        trace = AgentTrace(question=question)
        system = self._system_prompt()
        transcript = f"Question: {question}"

        # Root span = one trace per answer. Every step/tool span nests inside it,
        # so a single answer opens as one tree in Langfuse / any OTel backend.
        async with self._tracer.span(
            "agent.run", tenant_id=str(ctx.tenant_id), question=question
        ) as root:
            result = await self._run_steps(ctx, question, system, transcript, trace, root)
            root.set_attributes(
                stop_reason=trace.stop_reason,
                num_steps=trace.num_steps,
                tokens_used=trace.tokens_used,
                tools_used=",".join(trace.tools_used()),
            )
            return result

    async def _run_steps(
        self, ctx: ToolContext, question: str, system: str, transcript: str, trace: AgentTrace, root
    ) -> AgentResult:  # type: ignore[no-untyped-def]
        for step_index in range(self._max_steps):
            async with self._tracer.span("agent.step", index=step_index) as step_span:
                decision = self._router.route(question, step_index=step_index)
                raw = await decision.provider.generate(system, transcript)
                trace.tokens_used += raw.tokens_used
                trace.provider = raw.provider
                step_span.record_generation(
                    model=raw.model,
                    provider=raw.provider,
                    prompt=transcript,
                    completion=raw.text,
                    tokens=raw.tokens_used,
                )

                thought, action, action_input, parse_error = _parse_action(raw.text)
                step = AgentStep(
                    index=step_index,
                    thought=thought,
                    action=action,
                    action_input=action_input,
                    model=f"{decision.tier}:{raw.model}",
                )
                step_span.set_attributes(action=action, thought=thought)

                if parse_error:
                    step.observation = (
                        f"Your last message was not a single valid JSON action ({parse_error}). "
                        "Respond with exactly one JSON object."
                    )
                    trace.add(step)
                    transcript += f"\n\nObservation: {step.observation}"
                    continue

                if action == "final":
                    answer = str(action_input.get("answer", "")).strip() or self._refusal
                    step.observation = "(final answer)"
                    trace.add(step)
                    trace.final_answer = answer
                    trace.stop_reason = "final"
                    return AgentResult(answer=answer, trace=trace)

                tool = self._registry.get(action)
                if tool is None:
                    step.observation = (
                        f"Unknown tool {action!r}. "
                        f"Available: {', '.join(self._registry.names())}."
                    )
                    trace.add(step)
                    transcript += f"\n\nObservation: {step.observation}"
                    continue

                await self._invoke_tool(tool, ctx, action, action_input, step)
                trace.add(step)
                transcript += (
                    f"\n\nThought: {thought}\nAction: {action}\nObservation: {step.observation}"
                )

        # Budget exhausted without a `final`. Make one last grounded attempt from
        # whatever was observed rather than returning nothing.
        trace.stop_reason = "max_steps"
        decision = self._router.route(question, step_index=self._max_steps)
        closing = await decision.provider.generate(
            system + "\nYou are out of steps. Answer now using only the observations above.",
            transcript + "\n\nProvide your final answer as plain text.",
        )
        trace.tokens_used += closing.tokens_used
        answer = closing.text.strip() or self._refusal
        trace.final_answer = answer
        return AgentResult(answer=answer, trace=trace)

    async def _invoke_tool(self, tool, ctx, action, action_input, step) -> None:  # type: ignore[no-untyped-def]
        async with self._tracer.span(f"tool.{action}", **action_input) as tool_span:
            try:
                result = await tool.run(ctx, **action_input)
                step.observation = result.observation
                step.data = result.data
                # Surface retrieval strength as a span score (the "review outputs"
                # signal): the top similarity of whatever this tool returned.
                scores = [c.get("score", 0.0) for c in result.data.get("citations", [])]
                if scores:
                    tool_span.score("top_retrieval_score", max(scores))
                tool_span.set_attributes(observation=result.observation[:500])
            except Exception as exc:  # noqa: BLE001 - surface tool errors to the planner
                log.warning("agent.tool_error", tool=action, error=str(exc))
                step.observation = f"Tool {action!r} raised an error: {exc}"
                tool_span.record_exception(exc)


def _parse_action(text: str) -> tuple[str, str, dict, str | None]:
    """Extract (thought, action, action_input, error) from a planner message.

    Tolerant of markdown fences / surrounding prose by grabbing the first JSON
    object. Returns a non-None error string when nothing usable is found, so the
    loop can ask the model to retry instead of raising.
    """
    match = _JSON_OBJECT.search(text)
    if not match:
        return "", "", {}, "no JSON object found"
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError as exc:
        return "", "", {}, f"invalid JSON: {exc.msg}"
    if not isinstance(data, dict) or "action" not in data:
        return "", "", {}, "missing 'action' field"
    action_input = data.get("action_input", {})
    if not isinstance(action_input, dict):
        action_input = {}
    return (
        str(data.get("thought", "")),
        str(data["action"]),
        action_input,
        None,
    )
