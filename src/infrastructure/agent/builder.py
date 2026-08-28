"""Assemble a ready-to-run `AgentLoop` from the composition root.

Keeps the agent wiring (which tools exist, how the router is tiered, the step
budget, the refusal string) in one place so the container stays a thin list of
singletons and the API layer never touches concrete agent internals.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from src.application.agent.loop import AgentLoop
from src.application.agent.registry import ToolRegistry
from src.application.agent.router import ModelRouter
from src.domain.chatbot.entities import DEFAULT_SYSTEM_PROMPT  # noqa: F401 (doc anchor)
from src.infrastructure.agent.document_search_tool import DocumentSearchTool
from src.infrastructure.agent.scheduling_tools import build_scheduling_tools

if TYPE_CHECKING:
    from src.config.container import Container

# The exact off-topic redirect the agent emits — kept in sync with the RAG path's
# opener so the eval harness's `refusal_correct` recognises both.
AGENT_REFUSAL = (
    "I'm here to help with our open roles and your application. "
    "I can't help with that request, but I'm happy to tell you about our roles or "
    "help with your candidacy."
)


def build_agent_loop(container: Container) -> AgentLoop:
    tools = [
        DocumentSearchTool(
            uow_factory=container.unit_of_work,
            embedder=container.embedder,
            default_top_k=container.settings.retrieval_top_k,
        ),
        # Future tools (SQL/analytics, web, ticketing) register here — the
        # loop and the API layer need no changes to gain a new capability.
    ]
    # Appointment booking. Gated because adding tools to the catalogue changes
    # how the existing document-answering agent behaves, and nothing is wired to
    # book yet — see APPOINTMENT_AGENT_TOOLS_ENABLED in config/settings.py.
    #
    # The tools themselves enforce spec section 61: the model cannot produce an
    # appointment time, because every slot it can offer came from the
    # availability engine.
    if container.settings.appointment_agent_tools_enabled:
        tools.extend(build_scheduling_tools(container.unit_of_work))
    registry = ToolRegistry(tools)
    # One failover LLM today => cheap and strong tiers coincide; the router seam
    # is in place for when a second (stronger) model is configured.
    router = ModelRouter(cheap=container.llm, strong=container.llm)
    return AgentLoop(
        registry,
        router,
        refusal_answer=AGENT_REFUSAL,
        max_steps=container.settings.agent_max_steps,
        tracer=container.tracer,
    )
