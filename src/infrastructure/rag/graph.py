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
from src.config.settings import get_settings
from src.domain.chat.entities import Citation
from src.domain.chat.relevance import prune_citations
from src.domain.chatbot.entities import Chatbot
from src.domain.safety.guardrails import NO_CONTEXT_MARKER, build_grounded_prompt


class RAGState(TypedDict, total=False):
    chatbot: Chatbot
    question: str
    citations: list[Citation]
    context: str
    answer: str
    tokens_used: int
    provider: str


def _effective_min_score(bot: Chatbot) -> float:
    """The assistant's own floor, or the platform's, whichever is stricter.
    Matches `AskChatbot._retrieve`, so the streaming and non-streaming paths
    cannot answer the same question from different evidence."""
    return max(bot.retrieval.min_score, get_settings().retrieval_min_score_floor)


def build_context(citations: list[Citation]) -> str:
    # The exact marker matters: `build_grounded_prompt` keys its strict
    # "you have no sources" wording off it, so a paraphrase here silently puts
    # the widget and streaming paths back on the hedged instructions.
    if not citations:
        return NO_CONTEXT_MARKER
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
            min_score=_effective_min_score(bot),
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
        # A hard-coded max(..., 0.65) once lived here. It silently overrode
        # lower configs and emptied the context for most queries
        # (gemini-embedding-001 cosine scores rarely clear 0.65), which made the
        # model fall back to general knowledge — so the floor is now low and
        # tunable, and the scale-free relative cut does the real filtering.
        relevant = prune_citations(
            state.get("citations", []), min_score=_effective_min_score(bot)
        )
        state["citations"] = relevant
        state["context"] = build_context(relevant)
        return state

    async def _generate(self, state: RAGState) -> RAGState:
        bot = state["chatbot"]
        # Isolate untrusted context + question in labelled blocks (injection
        # defence); pairs with the hardened grounding system prompt.
        prompt = build_grounded_prompt(state["context"], state["question"])
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
