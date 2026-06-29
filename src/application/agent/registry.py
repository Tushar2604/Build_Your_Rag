"""A small name→Tool registry the loop and planner share."""

from __future__ import annotations

from src.application.agent.tools import Tool, ToolSpec


class ToolRegistry:
    def __init__(self, tools: list[Tool] | None = None) -> None:
        self._tools: dict[str, Tool] = {}
        for tool in tools or []:
            self.register(tool)

    def register(self, tool: Tool) -> None:
        name = tool.spec.name
        if name in self._tools:
            raise ValueError(f"duplicate tool name: {name!r}")
        self._tools[name] = tool

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def specs(self) -> list[ToolSpec]:
        return [t.spec for t in self._tools.values()]

    def names(self) -> list[str]:
        return list(self._tools)

    def render_catalog(self) -> str:
        """Human/LLM-readable tool list for the planner system prompt."""
        lines: list[str] = []
        for spec in self.specs():
            params = ", ".join(
                f"{k}: {v.get('type', 'string')}" for k, v in spec.parameters.items()
            )
            sig = f"{spec.name}({params})"
            lines.append(f"- {sig}\n    {spec.description}")
        return "\n".join(lines)
