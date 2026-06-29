"""LangGraph RAG pipeline.

Defines the retrieval-augmented generation flow as an explicit, inspectable
graph: `retrieve -> assemble -> generate`. Making it a graph (rather than an
ad-hoc function) means each node is independently testable, the flow is easy to
visualise, and we can later insert nodes (rerank, guardrail, query-rewrite)
without rewriting the pipeline.

The graph runs the non-streaming path. The streaming chat endpoint reuses the
`retrieve` + `assemble` nodes, then streams `generate` token-by-token over SSE.
"""

from __future__ import annotations

from typing import TypedDict

from langgraph.graph import END, StateGraph

from src.application.ports.repositories import ChunkRepository
from src.application.ports.services import Embedder, LLMProvider
from src.domain.chat.entities import Citation
from src.domain.chatbot.entities import Chatbot


class RAGState(TypedDict, total=False):
    chatbot: Chatbot
    question: str
    citations: list[Citation]
    context: str
    answer: str
    tokens_used: int
    provider: str


def build_context(citations: list[Citation]) -> str:
    if not citations:
        return "(no relevant context found)"
    return "\n\n".join(
        f"[Source {c.ordinal} | doc={c.document_id} | score={c.score:.3f}]\n{c.snippet}"
        for c in citations
    )


class RagGraph:
    def __init__(
        self, chunks: ChunkRepository, embedder: Embedder, llm: LLMProvider
    ) -> None:
        self._chunks = chunks
        self._embedder = embedder
        self._llm = llm
        self._graph = self._compile()

    async def _retrieve(self, state: RAGState) -> RAGState:
        bot = state["chatbot"]
        vec = await self._embedder.embed_query(state["question"])
        hits = await self._chunks.search(
            tenant_id=bot.tenant_id,
            query_embedding=vec,
            top_k=bot.retrieval.top_k,
            document_ids=bot.document_filter(),
            min_score=bot.retrieval.min_score,
        )
        state["citations"] = [
            Citation(
                document_id=c.document_id,
                chunk_id=c.id,
                ordinal=c.ordinal,
                score=score,
                snippet=c.text[:500],
            )
            for c, score in hits
        ]
        return state

    async def _assemble(self, state: RAGState) -> RAGState:
        bot = state["chatbot"]
        # Respect the chatbot's configured floor only. The previous hard-coded
        # max(..., 0.65) silently overrode lower configs and emptied the context
        # for most queries (gemini-embedding-001 cosine scores rarely clear
        # 0.65), which made the model fall back to general knowledge. It also
        # diverged from the streaming path, which filters solely in `search`.
        floor = bot.retrieval.min_score
        relevant = [c for c in state.get("citations", []) if c.score >= floor]
        state["citations"] = relevant
        state["context"] = build_context(relevant)
        return state

    async def _generate(self, state: RAGState) -> RAGState:
        bot = state["chatbot"]
        prompt = f"Context:\n{state['context']}\n\nQuestion: {state['question']}"
        result = await self._llm.generate(bot.system_prompt, prompt)
        state["answer"] = result.text
        state["tokens_used"] = result.tokens_used
        state["provider"] = result.provider
        return state

    def _compile(self):  # type: ignore[no-untyped-def]
        g = StateGraph(RAGState)
        g.add_node("retrieve", self._retrieve)
        g.add_node("assemble", self._assemble)
        g.add_node("generate", self._generate)
        g.set_entry_point("retrieve")
        g.add_edge("retrieve", "assemble")
        g.add_edge("assemble", "generate")
        g.add_edge("generate", END)
        return g.compile()

    async def run(self, chatbot: Chatbot, question: str) -> RAGState:
        return await self._graph.ainvoke({"chatbot": chatbot, "question": question})

    async def retrieve_only(self, chatbot: Chatbot, question: str) -> list[Citation]:
        """Used by the streaming endpoint, which streams generation separately."""
        state = await self._retrieve({"chatbot": chatbot, "question": question})
        return state.get("citations", [])
