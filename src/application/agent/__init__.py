"""Agentic orchestration layer.

The single-shot RAG path (`AskChatbot` / `RagGraph`) always does exactly one
retrieval then one generation. An *agent* instead decides — per turn — which tool
to use, can take several steps (search, refine the query, search again), and can
choose to answer directly or refuse. This is the "agents platform" layer:

  * `tools`    — the `Tool` port plus the `ToolContext`/`ToolResult` value types.
  * `registry` — a name→Tool map exposed to the planner.
  * `router`   — picks a model tier per turn (cheap by default, escalate on hard
                 questions) so cost tracks difficulty.
  * `loop`     — a provider-agnostic ReAct loop (think→act→observe) built on the
                 existing `LLMProvider.generate`, with a hard step budget.
  * `trace`    — a structured record of every step, for observability/eval.

Everything here depends only on application ports, so concrete tools (document
search, SQL, web) live in `infrastructure/agent` and are injected at the
composition root — same hexagonal direction as the rest of the codebase.
"""

from __future__ import annotations

from src.application.agent.loop import AgentLoop, AgentResult
from src.application.agent.registry import ToolRegistry
from src.application.agent.router import ModelRouter
from src.application.agent.tools import Tool, ToolContext, ToolResult, ToolSpec
from src.application.agent.trace import AgentStep, AgentTrace

__all__ = [
    "AgentLoop",
    "AgentResult",
    "AgentStep",
    "AgentTrace",
    "ModelRouter",
    "Tool",
    "ToolContext",
    "ToolRegistry",
    "ToolResult",
    "ToolSpec",
]
