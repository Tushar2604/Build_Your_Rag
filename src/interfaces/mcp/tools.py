"""MCP tool implementations — pure async functions over the composition root.

Kept free of any MCP-SDK import so they unit-test with a fake container and so
the protocol layer (`server.py`) stays a thin registration shim. Every function
is tenant-scoped: the tenant is resolved once from an API key and threaded
through, mirroring the HTTP API's `X-API-Key` access-control model — an MCP
client never selects its own tenant.
"""

from __future__ import annotations

from dataclasses import dataclass

from src.domain.shared.identifiers import ChatbotId, TenantId
from src.infrastructure.security.hashing import hash_api_key


class McpAuthError(Exception):
    """The configured MCP API key did not resolve to a tenant."""


@dataclass(frozen=True)
class McpAuth:
    """The resolved scope an MCP session operates within."""

    tenant_id: TenantId


async def resolve_tenant(container, api_key: str) -> McpAuth:  # type: ignore[no-untyped-def]
    """Map an API key to its tenant (same hash lookup as the HTTP API key auth)."""
    if not api_key:
        raise McpAuthError("MCP_TENANT_API_KEY is not set.")
    async with container.unit_of_work() as uow:
        record = await uow.api_keys.get_by_hash(hash_api_key(api_key))
    if record is None:
        raise McpAuthError("Invalid MCP API key.")
    return McpAuth(tenant_id=record.tenant_id)


async def search_documents(
    container, auth: McpAuth, query: str, top_k: int = 5
) -> dict:  # type: ignore[no-untyped-def]
    """Semantic search over the tenant's corpus. Returns ranked passages."""
    if not query.strip():
        return {"query": query, "results": [], "note": "empty query"}
    top_k = max(1, min(int(top_k), 20))

    vec = await container.embedder.embed_query(query)
    async with container.unit_of_work() as uow:
        uow.set_tenant_scope(auth.tenant_id)
        hits = await uow.chunks.search(
            tenant_id=auth.tenant_id,
            query_embedding=vec,
            top_k=top_k,
            document_ids=None,
            min_score=0.0,
        )
    return {
        "query": query,
        "results": [
            {
                "document_id": str(chunk.document_id),
                "chunk_id": str(chunk.id),
                "ordinal": chunk.ordinal,
                "score": round(score, 4),
                "snippet": chunk.text[:800],
            }
            for chunk, score in hits
        ],
    }


async def list_documents(container, auth: McpAuth) -> dict:  # type: ignore[no-untyped-def]
    """List the tenant's documents and their ingestion status."""
    async with container.unit_of_work() as uow:
        uow.set_tenant_scope(auth.tenant_id)
        docs = await uow.documents.list_for_tenant(auth.tenant_id)
    return {
        "count": len(docs),
        "documents": [
            {
                "id": str(d.id),
                "filename": d.filename,
                "status": str(d.status),
                "chunk_count": d.chunk_count,
                "error": d.error,
            }
            for d in docs
        ],
    }


async def answer_question(
    container, auth: McpAuth, chatbot_id: str, message: str
) -> dict:  # type: ignore[no-untyped-def]
    """Answer a question with the multi-step agent over a specific chatbot.

    Reuses the same `RunAgent` use case (and therefore the same quota, rate
    limiting, and tracing) as the HTTP endpoint — the MCP surface adds no new
    answer path, it just exposes the existing one.
    """
    from src.application.agent.tools import ToolContext

    async with container.unit_of_work() as uow:
        uow.set_tenant_scope(auth.tenant_id)
        chatbot = await uow.chatbots.get(auth.tenant_id, ChatbotId(_to_uuid(chatbot_id)))
    if chatbot is None:
        return {"error": f"chatbot {chatbot_id} not found"}

    ctx = ToolContext(
        tenant_id=auth.tenant_id,
        chatbot_id=chatbot.id,
        extras={"allowed_document_ids": chatbot.allowed_document_ids or None},
    )
    result = await container.agent_loop.run(ctx, message)
    return {
        "answer": result.answer,
        "stop_reason": result.trace.stop_reason,
        "tools_used": result.trace.tools_used(),
        "tokens_used": result.trace.tokens_used,
    }


def _to_uuid(value: str):  # type: ignore[no-untyped-def]
    import uuid

    return uuid.UUID(str(value))
