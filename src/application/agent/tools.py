"""The Tool port and its value types.

A tool is the unit of capability an agent can invoke: it has a name, a
description and parameter schema the planner sees, and an async `run`. Tools
depend on the application ports only; concrete tools (document search, SQL, …)
live in the infrastructure layer and are registered at the composition root.

`ToolContext` carries the per-call request scope — crucially `tenant_id`, so a
tool can enforce the same tenant isolation as the rest of the stack (access
control is not optional just because a model asked for the data).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from src.domain.shared.identifiers import ChatbotId, TenantId


@dataclass(frozen=True)
class ToolSpec:
    """The planner-facing description of a tool.

    `parameters` is a minimal JSON-schema-ish dict ({name: {"type", "description"}})
    rendered into the planner prompt. We keep it lightweight rather than full JSON
    Schema because the loop targets plain `generate()` providers, not a native
    tool-calling API — portability over Groq and Gemini both.
    """

    name: str
    description: str
    parameters: dict[str, dict[str, str]] = field(default_factory=dict)


@dataclass(frozen=True)
class ToolContext:
    """Per-invocation scope handed to every tool call. Tenant-scoped by design."""

    tenant_id: TenantId
    chatbot_id: ChatbotId | None = None
    # Free-form per-request metadata (e.g. allowed_document_ids, locale).
    extras: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ToolResult:
    """What a tool returns to the loop.

    `observation` is the text fed back to the planner. `data` carries structured
    payload (e.g. retrieved citations) the use case persists/returns without
    re-parsing the observation string. `ok=False` surfaces a handled tool error
    as an observation the agent can react to, instead of raising."""

    observation: str
    data: dict[str, Any] = field(default_factory=dict)
    ok: bool = True


@runtime_checkable
class Tool(Protocol):
    spec: ToolSpec

    async def run(self, ctx: ToolContext, **kwargs: Any) -> ToolResult: ...
