"""`search_documents` — the agent's grounding tool over the pgvector store.

Wraps exactly the retrieval the single-shot RAG path uses (embed the query, run a
tenant-scoped vector search), but exposes it as an agent `Tool` so the loop can
call it zero, one, or several times per question. Tenant isolation is enforced
here from `ToolContext.tenant_id` — a model asking for data never widens scope.

Each call opens its own short-lived unit of work (matching `AskChatbot`'s pattern
of never holding a DB connection across the embedding network call), keeping the
free-tier connection pool happy.
"""

from __future__ import annotations

from typing import Any

from src.application.agent.tools import ToolContext, ToolResult, ToolSpec
from src.application.ports.repositories import UnitOfWork
from src.application.ports.services import Embedder
from src.domain.shared.identifiers import DocumentId

_MIN_SCORE = 0.65  # mirror the assemble-step relevance floor in RagGraph


class DocumentSearchTool:
    spec = ToolSpec(
        name="search_documents",
        description=(
            "Search the tenant's document corpus for passages relevant to a query. "
            "Returns ranked snippets with a similarity score and source document id. "
            "Call this before answering any factual question."
        ),
        parameters={
            "query": {"type": "string", "description": "natural-language search query"},
            "top_k": {"type": "integer", "description": "max passages to return (default 5)"},
        },
    )

    def __init__(self, uow_factory, embedder: Embedder, *, default_top_k: int = 5) -> None:
        # uow_factory() -> UnitOfWork (e.g. container.unit_of_work)
        self._uow_factory = uow_factory
        self._embedder = embedder
        self._default_top_k = default_top_k

    async def run(self, ctx: ToolContext, **kwargs: Any) -> ToolResult:
        query = str(kwargs.get("query", "")).strip()
        if not query:
            return ToolResult(observation="No query provided.", ok=False)
        top_k = int(kwargs.get("top_k") or self._default_top_k)

        doc_filter = ctx.extras.get("allowed_document_ids") or None
        document_ids = (
            [DocumentId(d) if not isinstance(d, DocumentId) else d for d in doc_filter]
            if doc_filter
            else None
        )

        # Embed outside any transaction, then a short read-only search txn.
        vec = await self._embedder.embed_query(query)
        uow: UnitOfWork = self._uow_factory()
        async with uow:
            uow.set_tenant_scope(ctx.tenant_id)
            hits = await uow.chunks.search(
                tenant_id=ctx.tenant_id,
                query_embedding=vec,
                top_k=top_k,
                document_ids=document_ids,
                min_score=_MIN_SCORE,
            )

        if not hits:
            return ToolResult(
                observation="No relevant passages found in the documents.",
                data={"citations": []},
            )

        citations = [
            {
                "document_id": str(chunk.document_id),
                "chunk_id": str(chunk.id),
                "ordinal": chunk.ordinal,
                "score": round(score, 4),
                "snippet": chunk.text[:500],
            }
            for chunk, score in hits
        ]
        observation = "\n\n".join(
            f"[doc={c['document_id']} score={c['score']}]\n{c['snippet']}" for c in citations
        )
        return ToolResult(observation=observation, data={"citations": citations})
