"""Hiring Agent MCP client — structured error hierarchy.

All MCP client failures raise a subclass of `MCPError` so callers can
catch the base type for broad handling or a specific subclass for targeted
recovery. None of these errors are exposed on the HTTP surface; tools
convert them to `ToolResult(ok=False)`.
"""

from __future__ import annotations


class MCPError(Exception):
    """Base class for all Hiring Agent MCP client failures."""


class MCPNotInstalledError(MCPError):
    """The `mcp` optional dependency is not installed.

    Install with:  pip install 'rag-platform[mcp]'
    """


class MCPConnectionError(MCPError):
    """Failed to establish or maintain a connection to an MCP server.

    This is the only error class that triggers the retry policy — transient
    network / process-startup failures are worth retrying; tool errors and
    timeouts are not.
    """


class MCPTimeoutError(MCPError):
    """An MCP tool call exceeded the configured per-call timeout."""

    def __init__(self, tool_name: str, timeout_seconds: float) -> None:
        self.tool_name = tool_name
        self.timeout_seconds = timeout_seconds
        super().__init__(f"Tool '{tool_name}' timed out after {timeout_seconds}s")


class MCPToolError(MCPError):
    """The MCP server returned an error response for a tool invocation.

    Not retried — the server responded; the error is deterministic.
    """

    def __init__(self, tool_name: str, detail: str) -> None:
        self.tool_name = tool_name
        self.detail = detail
        super().__init__(f"Tool '{tool_name}' returned an error: {detail}")


class MCPRetryExhausted(MCPError):
    """All retry attempts for an MCP tool call were exhausted."""

    def __init__(self, tool_name: str, attempts: int, cause: BaseException) -> None:
        self.tool_name = tool_name
        self.attempts = attempts
        self.cause = cause
        super().__init__(
            f"Tool '{tool_name}' failed after {attempts} attempt(s): {cause}"
        )


class MCPServerNotFoundError(MCPError):
    """No registered MCP server provides the requested tool."""

    def __init__(self, tool_name: str) -> None:
        self.tool_name = tool_name
        super().__init__(
            f"No MCP server registered for tool '{tool_name}'. "
            "Check HIRING_MCP_SERVERS and ensure the server is reachable."
        )
