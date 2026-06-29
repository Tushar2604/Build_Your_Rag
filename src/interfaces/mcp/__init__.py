"""MCP (Model Context Protocol) server — exposes the RAG corpus as agent tools.

This makes the platform a *connector*: any MCP client (Claude Desktop, an
internal agent, an IDE) can search a tenant's documents, list them, and ask the
chatbot, without touching the HTTP API directly.

Layering keeps the protocol glue thin and the logic testable:
  * `tools`  — SDK-independent async functions that do the real work against the
               composition root. Unit-tested with a fake container, no MCP SDK.
  * `server` — a `FastMCP` wrapper that resolves the tenant from an API key and
               registers the `tools` functions as MCP tools.

Run it (stdio transport, for Claude Desktop / mcp clients):
    MCP_TENANT_API_KEY=sk_... python -m src.interfaces.mcp.server
"""

from __future__ import annotations

__all__ = ["__doc__"]
