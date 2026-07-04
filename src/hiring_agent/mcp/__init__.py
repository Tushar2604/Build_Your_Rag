"""Hiring Agent MCP client package.

Exports `get_hiring_mcp_client()` — a lazy singleton that returns the
shared `MCPClientManager` for this process.  Tools call this function
instead of constructing their own client, ensuring discovery runs once.
"""

from __future__ import annotations

from src.hiring_agent.mcp.client import MCPClientManager
from src.hiring_agent.mcp.config import load_hiring_mcp_servers
from src.hiring_agent.mcp.errors import (
    MCPConnectionError,
    MCPError,
    MCPNotInstalledError,
    MCPRetryExhausted,
    MCPServerNotFoundError,
    MCPTimeoutError,
    MCPToolError,
)

_client: MCPClientManager | None = None


def get_hiring_mcp_client() -> MCPClientManager:
    """Return (or lazily create) the process-wide MCP client manager."""
    global _client
    if _client is None:
        _client = MCPClientManager(load_hiring_mcp_servers())
    return _client


__all__ = [
    "MCPClientManager",
    "MCPConnectionError",
    "MCPError",
    "MCPNotInstalledError",
    "MCPRetryExhausted",
    "MCPServerNotFoundError",
    "MCPTimeoutError",
    "MCPToolError",
    "get_hiring_mcp_client",
]
