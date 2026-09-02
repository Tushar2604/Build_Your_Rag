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
from datetime import UTC, datetime

import structlog

from src.application.agent.registry import ToolRegistry
from src.application.agent.router import ModelRouter
from src.application.agent.tools import ToolContext
from src.application.agent.trace import AgentStep, AgentTrace
from src.application.ports.observability import NoOpTracer, Tracer
from src.domain.chatbot.entities import RESPONSE_LANGUAGE_AUTO
from src.domain.safety.guardrails import language_rules

log = structlog.get_logger(__name__)

_JSON_OBJECT = re.compile(r"\{.*\}", re.DOTALL)

# A stable, non-brace marker rather than a `{business_context}` format field.
# The text it is replaced with is a tenant's own Conversational Flow — free
# text an operator typed into a browser, which can contain literal `{` or `}`
# (a pasted JSON example, a stray curly quote). Feeding that through
# `str.format()` would raise on the operator's own content; `str.replace()`
# treats it as inert text, which is what "we don't control this string" means.
_BUSINESS_CONTEXT_MARKER = "<<BUSINESS_CONTEXT>>"
_LANGUAGE_RULES_MARKER = "<<LANGUAGE_RULES>>"

# Appended to every system prompt this loop renders, tenant content or not.
# Both rules exist because of the same failure: the loop had no fallback for
# either question, so a weaker model either dodged ("I'm an AI assistant...")
# or echoed a template placeholder it did not know how to fill
# (a literal "Hi [name]," sent to a real customer). Neither is a tenant
# setting — every assistant on the platform benefits from both being fixed.
_IDENTITY_AND_VOICE = """
IDENTITY
  If asked who or what you are, answer warmly and naturally, the way a real \
person on the team would — never say "AI", "bot", "model", "assistant", \
"virtual", or "language model", and never dodge the question. Give yourself a \
first name if the business identity above does not already give you one, and \
once you have used a name in this conversation, keep using that same one — \
check the conversation so far before picking a new one. Answer briefly, then \
move on: "I'm Maya, happy to help — what can I do for you?" is the shape, not \
a script to copy.

NEVER SHOW A PLACEHOLDER
  If the business identity above (or your own draft answer) contains a \
bracket like [name] or [user_name] and you do not have a real value for it, \
do NOT write the bracket itself. Rephrase naturally without it, or ask for the \
detail instead. A customer must never see literal square brackets in a message \
— that is a template you forgot to fill in, not something to send.
"""


def _render_business_context(tenant_prompt: str) -> str:
    """The block that tells this loop which business it is actually working for.

    Without this, the loop's own tool-use rules are the entire personality the
    model has — which is why an assistant with a fully written Conversational
    Flow (its identity, its facts, its own do's and don'ts) still answered like
    a generic template on any channel that ran through this loop instead of the
    plain retrieval path. Whatever the tenant configured takes priority for
    facts, tone and business rules; it never overrides the loop's own tool-use
    and safety rules below it, which are the platform's, not the tenant's.
    """
    text = tenant_prompt.strip()
    if not text:
        return (
            "(No business details are configured for this assistant yet. Be "
            "honest that you don't have specifics rather than inventing any, "
            "and keep the rules below.)"
        )
    return (
        "The following is this business's own configuration — its identity, "
        "facts, and how it wants you to behave. Follow it for tone, facts and "
        "business rules; it never overrides the rules below it.\n\n"
        f"{text}"
    )


_SYSTEM_TEMPLATE = """You are a warm, friendly, and genuinely helpful assistant \
answering questions about a specific set of documents. You must ground every \
answer in tool results — never answer from your own prior knowledge.

ABOUT THIS BUSINESS
<<BUSINESS_CONTEXT>>

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
<<IDENTITY_AND_VOICE>>

<<LANGUAGE_RULES>>
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
        system_template: str | None = None,
    ) -> None:
        self._registry = registry
        self._router = router
        self._refusal = refusal_answer
        self._max_steps = max_steps
        self._tracer = tracer or NoOpTracer()
        # Injectable so one loop can serve different jobs. The document-answering
        # agent and the front-office booking agent share all the ReAct machinery
        # — step budget, defensive action parsing, tracing — and differ only in
        # their tools and in how they are told to behave. Defaulting to the
        # original template leaves every existing caller unchanged.
        self._system_template = system_template or _SYSTEM_TEMPLATE

    def _system_prompt(
        self, tenant_prompt: str = "", response_language: str = RESPONSE_LANGUAGE_AUTO
    ) -> str:
        """Render the template: today's date, the tool catalog, and — the part
        that used to be missing — which business this actually is.

        `tenant_prompt` is inserted via `str.replace()`, after `.format()` has
        already consumed the template's own `{catalog}`/`{refusal}`/`{today}`
        fields. It has to happen in that order and with that method: the
        tenant's own text is not ours to control, `.format()` would raise on a
        stray `{` inside it, and `replace()` treats the marker as inert text
        rather than a field to fill.

        A model has no clock. Without being told the date it cannot resolve
        "tomorrow" or "Monday" into anything a tool will accept, and the failure
        looks like "no availability" rather than like a mistake — which is how an
        AI receptionist tells someone the business is shut on a day it is open.
        """
        rendered = self._system_template.format(
            catalog=self._registry.render_catalog(),
            refusal=self._refusal,
            today=datetime.now(UTC).strftime("%A %d %B %Y"),
        )
        rendered = rendered.replace(
            _BUSINESS_CONTEXT_MARKER, _render_business_context(tenant_prompt)
        )
        rendered = rendered.replace("<<IDENTITY_AND_VOICE>>", _IDENTITY_AND_VOICE)
        return rendered.replace(_LANGUAGE_RULES_MARKER, language_rules(response_language))

    async def run(
        self,
        ctx: ToolContext,
        question: str,
        *,
        history: str = "",
        tenant_prompt: str = "",
        response_language: str = RESPONSE_LANGUAGE_AUTO,
    ) -> AgentResult:
        """Answer `question`, optionally in the context of a conversation.

        `history` is what makes anything multi-turn possible. Booking is a
        conversation — "I need physio", "tomorrow evening", "6:15 works" — and
        each of those turns is meaningless alone. Without the prior turns the
        planner re-asks which service they wanted on every single message.

        `tenant_prompt` is the assistant's own Conversational Flow — its
        Identity, Facts, and business rules, exactly as configured in the
        builder. Without it, this loop's fixed tool-use rules are the entire
        personality the model has, on every channel that reaches it — which is
        indistinguishable from a generic template no matter how carefully an
        operator wrote their own.

        `response_language` is the assistant's own language policy — see
        `guardrails.language_rules` for what each value means. Defaults to the
        auto-mirror behaviour so a caller that omits it keeps working exactly
        as it always did.
        """
        trace = AgentTrace(question=question)
        system = self._system_prompt(tenant_prompt, response_language)
        transcript = (
            f"Conversation so far:\n{history}\n\nLatest message: {question}"
            if history
            else f"Question: {question}"
        )

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
