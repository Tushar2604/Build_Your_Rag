"""Hiring Agent tools — shared MCP dispatch base class.

`BaseMCPTool.run()` is the single implementation of the Tool Protocol's
`run` method for every hiring tool.  Each concrete tool subclass only
needs to declare its `spec`; all MCP routing, timeout, retry, error
handling, and logging are inherited from here.
"""

from __future__ import annotations

from typing import Any

import structlog

from src.application.agent.tools import ToolContext, ToolResult, ToolSpec
from src.hiring_agent.mcp.errors import MCPError, MCPNotInstalledError

log = structlog.get_logger(__name__)


class BaseMCPTool:
    """Base for hiring tools that delegate every call to an MCP server.

    Subclasses declare a class-level `spec: ToolSpec` and inherit `run()`.
    No business logic or mock data lives here — it lives in the MCP server.
    """

    spec: ToolSpec  # set by each concrete subclass

    async def run(self, ctx: ToolContext, **kwargs: Any) -> ToolResult:
        from src.hiring_agent.mcp import get_hiring_mcp_client

        tool_name = self.spec.name
        # Strip None values so server defaults take effect.
        params = {k: v for k, v in kwargs.items() if v is not None}

        log.info(
            "hiring.tool.invoke",
            tool=tool_name,
            tenant=str(ctx.tenant_id),
            params=params,
        )

        try:
            client = get_hiring_mcp_client()
            data = await client.call_tool(tool_name, params)
            observation = data.get(
                "observation", f"Tool '{tool_name}' completed successfully."
            )
            log.info(
                "hiring.tool.ok",
                tool=tool_name,
                tenant=str(ctx.tenant_id),
                observation_len=len(observation),
            )
            return ToolResult(observation=observation, data=data, ok=True)

        except MCPNotInstalledError as exc:
            log.warning(
                "hiring.tool.mcp_not_installed",
                tool=tool_name,
                hint="pip install 'rag-platform[mcp]'",
            )
            return ToolResult(
                observation=(
                    f"[mcp not installed] Tool '{tool_name}' requires the mcp package. "
                    "Run: pip install 'rag-platform[mcp]'"
                ),
                data={"error": str(exc), "error_type": "MCPNotInstalledError"},
                ok=False,
            )

        except MCPError as exc:
            log.error(
                "hiring.tool.mcp_error",
                tool=tool_name,
                tenant=str(ctx.tenant_id),
                error_type=type(exc).__name__,
                error=str(exc),
            )
            return ToolResult(
                observation=f"[mcp error] {type(exc).__name__}: {exc}",
                data={"error": str(exc), "error_type": type(exc).__name__},
                ok=False,
            )
