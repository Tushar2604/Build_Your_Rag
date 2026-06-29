"""FastMCP server exposing the RAG corpus as MCP tools.

Thin protocol shim: it resolves the tenant once from `MCP_TENANT_API_KEY`, then
registers the SDK-independent functions in `tools.py` as MCP tools. All access is
scoped to that tenant — the connector inherits the platform's access-control
model rather than inventing its own.

Start it (stdio transport, the default for Claude Desktop and most MCP clients):

    MCP_TENANT_API_KEY=sk_xxx python -m src.interfaces.mcp.server

Then point an MCP client at this command. The client will see three tools:
`search_documents`, `list_documents`, and `answer_question`.
"""

from __future__ import annotations

import os

import structlog

from src.config.container import get_container
from src.interfaces.mcp import tools as impl
from src.interfaces.mcp.tools import McpAuth, resolve_tenant

log = structlog.get_logger(__name__)

_API_KEY_ENV = "MCP_TENANT_API_KEY"


def build_server():  # type: ignore[no-untyped-def]
    """Construct the FastMCP server with tenant-scoped tools registered.

    The MCP SDK is imported here (not at module top) so `tools.py` and its tests
    never require the dependency to be installed.
    """
    from mcp.server.fastmcp import FastMCP

    container = get_container()
    api_key = os.environ.get(_API_KEY_ENV, "")

    mcp = FastMCP("rag-platform")

    async def _auth() -> McpAuth:
        # Resolved per call so a rotated/revoked key takes effect without restart.
        return await resolve_tenant(container, api_key)

    @mcp.tool()
    async def search_documents(query: str, top_k: int = 5) -> dict:
        """Semantic search over the tenant's document corpus. Returns ranked
        passages with a similarity score and source document id."""
        return await impl.search_documents(container, await _auth(), query, top_k)

    @mcp.tool()
    async def list_documents() -> dict:
        """List the tenant's documents and their ingestion status."""
        return await impl.list_documents(container, await _auth())

    @mcp.tool()
    async def answer_question(chatbot_id: str, message: str) -> dict:
        """Answer a question with the multi-step RAG agent over a given chatbot."""
        return await impl.answer_question(container, await _auth(), chatbot_id, message)

    return mcp


def main() -> None:
    if not os.environ.get(_API_KEY_ENV):
        log.warning("mcp.no_api_key", hint=f"set {_API_KEY_ENV} to a tenant API key")
    server = build_server()
    server.run()  # stdio transport by default


if __name__ == "__main__":
    main()
