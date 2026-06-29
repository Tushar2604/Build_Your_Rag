"""The system under evaluation, behind a thin port.

The runner shouldn't care whether it's hitting the real RAG pipeline, an agent,
or an in-memory fake — it only needs to (1) ask a question and (2) see what was
retrieved and what was answered. `EvalTarget` is that seam, which also keeps the
metric tests fast (a fake target needs no DB or API keys).

`LiveTarget` adapts the production stack: it runs the same retrieve+generate path
as `AskChatbot`, against a real chatbot, using the container's embedder, chunk
repository (pgvector) and failover LLM.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable


@dataclass(frozen=True)
class TargetOutput:
    """What a target returns for one question.

    `retrieved_doc_ids` is ranked best-first (duplicates allowed — the metrics
    dedupe to document level). `context` is the assembled prompt context, fed to
    the faithfulness judge.
    """

    answer: str
    retrieved_doc_ids: list[str] = field(default_factory=list)
    context: str = ""
    tokens_used: int = 0
    provider: str | None = None


@runtime_checkable
class EvalTarget(Protocol):
    async def answer(self, question: str) -> TargetOutput: ...


class LiveTarget:
    """Runs the real retrieve→assemble→generate path for a specific chatbot.

    Constructed from the composition root so an eval run exercises exactly the
    code users hit. Imports the container lazily to keep `evals.metrics` importable
    (and unit-testable) without the full infrastructure stack installed.
    """

    def __init__(self, tenant_id, chatbot) -> None:  # type: ignore[no-untyped-def]
        self._tenant_id = tenant_id
        self._chatbot = chatbot

    @classmethod
    async def for_chatbot(cls, tenant_id, chatbot_id) -> LiveTarget:  # type: ignore[no-untyped-def]
        from src.config.container import get_container

        container = get_container()
        async with container.unit_of_work() as uow:
            uow.set_tenant_scope(tenant_id)
            chatbot = await uow.chatbots.get(tenant_id, chatbot_id)
        if chatbot is None:
            raise ValueError(f"chatbot {chatbot_id} not found for tenant {tenant_id}")
        return cls(tenant_id, chatbot)

    async def answer(self, question: str) -> TargetOutput:
        from src.config.container import get_container
        from src.infrastructure.rag.graph import RagGraph

        container = get_container()
        async with container.unit_of_work() as uow:
            uow.set_tenant_scope(self._tenant_id)
            graph = RagGraph(uow.chunks, container.embedder, container.llm)
            state = await graph.run(self._chatbot, question)
        citations = state.get("citations", [])
        return TargetOutput(
            answer=state.get("answer", ""),
            retrieved_doc_ids=[str(c.document_id) for c in citations],
            context=state.get("context", ""),
            tokens_used=state.get("tokens_used", 0),
            provider=state.get("provider"),
        )
