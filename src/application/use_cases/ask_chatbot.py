"""Answer a user message over a chatbot's documents (the RAG flow).

Orchestration steps (mirrored by the LangGraph graph in infrastructure):
  retrieve -> assemble context + citations -> enforce token quota -> generate
  -> persist message + record usage -> emit MessageAnswered.

The actual LLM call goes through a failover router (Groq primary, Gemini
fallback) supplied as the `llm` port, so free-tier rate limits degrade
gracefully instead of erroring.
"""

from __future__ import annotations

import time

import structlog

from src.application.dtos import AnswerOutput, AskInput, CitationOut
from src.application.ports.repositories import RequestLog, UnitOfWork
from src.application.ports.services import Embedder, LLMProvider, LLMResult
from src.domain.chat.entities import Citation, Message, MessageRole
from src.domain.chat.events import MessageAnswered
from src.domain.chatbot.entities import Chatbot
from src.domain.safety.guardrails import (
    GUARD_REFUSAL,
    build_grounded_prompt,
    format_message_history,
    scan_input,
    scan_output,
)
from src.domain.shared.errors import NotFoundError, QuotaExceededError
from src.domain.shared.identifiers import SessionId, TenantId

log = structlog.get_logger(__name__)

# The canonical redirect opener from DEFAULT_SYSTEM_PROMPT; heuristic for custom
# prompts, but no_context (citation-based) is the prompt-independent signal.
_REFUSAL_PREFIX = "I'm here to help with our open roles and your application"


def _build_context(citations: list[Citation]) -> str:
    blocks = [
        f"[Source {c.ordinal} | doc={c.document_id} | score={c.score:.3f}]\n{c.snippet}"
        for c in citations
    ]
    return "\n\n".join(blocks) if blocks else "(no relevant context found)"


def _retrieved_payload(citations: list[Citation]) -> list[dict]:
    return [
        {
            "chunk_id": c.chunk_id,
            "document_id": str(c.document_id),
            "ordinal": c.ordinal,
            "score": c.score,
        }
        for c in citations
    ]


def _max_score(citations: list[Citation]) -> float | None:
    return max((c.score for c in citations), default=None)


def _elapsed_ms(started: float) -> int:
    return int((time.perf_counter() - started) * 1000)


class AskChatbot:
    def __init__(self, uow: UnitOfWork, embedder: Embedder, llm: LLMProvider) -> None:
        self._uow = uow
        self._embedder = embedder
        self._llm = llm

    async def execute(
        self, tenant_id: TenantId, session_id: SessionId, data: AskInput
    ) -> AnswerOutput:
        started = time.perf_counter()
        # IMPORTANT: no DB connection is held across the embedding or LLM calls.
        # Free-tier Postgres (Neon) caps connections aggressively, so each
        # transaction below is short-lived and released before any slow network
        # call (embed / generate) runs.

        # --- 1. Validate, enforce quota, persist the user message (short txn) ---
        async with self._uow as uow:
            uow.set_tenant_scope(tenant_id)

            session = await uow.chats.get_session(tenant_id, session_id)
            if session is None:
                raise NotFoundError("Chat session not found.")
            chatbot = await uow.chatbots.get(tenant_id, session.chatbot_id)
            if chatbot is None:
                raise NotFoundError("Chatbot not found.")

            tenant = await uow.tenants.get(tenant_id)
            assert tenant is not None
            used = await uow.usage.tokens_used_today(tenant_id)
            if used >= tenant.daily_token_quota:
                raise QuotaExceededError("Daily token quota exceeded. Try again tomorrow.")

            # Fetched BEFORE the current message is added, so it reflects prior
            # turns only — the current message is passed separately as `data.message`.
            history_text = format_message_history(await uow.chats.list_messages(tenant_id, session_id))

            if data.persist_user_message:
                await uow.chats.add_message(
                    Message(
                        session_id=session_id,
                        tenant_id=tenant_id,
                        role=MessageRole.USER,
                        content=data.message,
                    )
                )
            await uow.commit()

        # --- 2. Retrieve (embedding + vector search, own short txn) ---
        citations = await self._retrieve(tenant_id, chatbot, data.message)

        # --- 3. Generate (NO transaction open — the slow call runs pool-free) ---
        # Guardrails wrap the generation: screen the user message for injection,
        # isolate untrusted text in labelled blocks, and screen the answer for
        # system-prompt leakage. A high-risk verdict short-circuits to a refusal.
        context = _build_context(citations)
        user_prompt = build_grounded_prompt(context, data.message, history=history_text)

        input_verdict = scan_input(data.message)
        if not input_verdict.allowed:
            log.warning(
                "guardrail.input_blocked",
                tenant_id=str(tenant_id),
                categories=input_verdict.categories,
            )
            result = LLMResult(
                text=GUARD_REFUSAL, tokens_used=0, provider="guardrail", model="guardrail"
            )
        else:
            try:
                result = await self._llm.generate(chatbot.system_prompt, user_prompt)
            except Exception as exc:  # noqa: BLE001 - record the failed request, then surface it
                await self._log_request(
                    tenant_id,
                    chatbot,
                    session_id,
                    data.message,
                    citations,
                    started,
                    status="error",
                    error=f"{type(exc).__name__}: {exc}",
                )
                raise

            output_verdict = scan_output(result.text, system_prompt=chatbot.system_prompt)
            if not output_verdict.allowed:
                log.warning(
                    "guardrail.output_blocked",
                    tenant_id=str(tenant_id),
                    categories=output_verdict.categories,
                )
                result = LLMResult(
                    text=GUARD_REFUSAL,
                    tokens_used=result.tokens_used,
                    provider=result.provider,
                    model=result.model,
                )

        refused = result.text.strip().startswith(_REFUSAL_PREFIX)

        # --- 4. Persist answer + usage + event + request log (short txn) ---
        answer = Message(
            session_id=session_id,
            tenant_id=tenant_id,
            role=MessageRole.ASSISTANT,
            content=result.text,
            citations=citations,
            tokens_used=result.tokens_used,
            provider=result.provider,
        )
        async with self._uow as uow:
            uow.set_tenant_scope(tenant_id)
            await uow.chats.add_message(answer)
            await uow.usage.add_tokens(tenant_id, result.tokens_used)
            await uow.request_logs.add(
                RequestLog(
                    tenant_id=tenant_id,
                    chatbot_id=chatbot.id,
                    session_id=session_id,
                    message_id=answer.id,
                    query=data.message,
                    retrieved=_retrieved_payload(citations),
                    num_retrieved=len(citations),
                    max_score=_max_score(citations),
                    no_context=not citations,
                    refused=refused,
                    answer=result.text,
                    provider=result.provider,
                    model=result.model,
                    tokens_used=result.tokens_used,
                    status="ok",
                    latency_ms=_elapsed_ms(started),
                )
            )
            uow.collect_event(
                MessageAnswered(
                    tenant_id=tenant_id,
                    session_id=session_id,
                    chatbot_id=chatbot.id,
                    tokens_used=result.tokens_used,
                    provider=result.provider,
                )
            )
            await uow.commit()

        return AnswerOutput(
            message_id=answer.id,
            answer=result.text,
            citations=[
                CitationOut(
                    document_id=c.document_id,
                    chunk_id=c.chunk_id,
                    ordinal=c.ordinal,
                    score=c.score,
                    snippet=c.snippet,
                )
                for c in citations
            ],
            tokens_used=result.tokens_used,
            provider=result.provider,
        )

    async def _log_request(
        self,
        tenant_id: TenantId,
        chatbot: Chatbot,
        session_id: SessionId,
        query: str,
        citations: list[Citation],
        started: float,
        *,
        status: str,
        error: str | None = None,
    ) -> None:
        """Write a request log in its own short txn. Never raises — a logging
        failure must not mask the original error or break the response."""
        try:
            async with self._uow as uow:
                uow.set_tenant_scope(tenant_id)
                await uow.request_logs.add(
                    RequestLog(
                        tenant_id=tenant_id,
                        chatbot_id=chatbot.id,
                        session_id=session_id,
                        query=query,
                        retrieved=_retrieved_payload(citations),
                        num_retrieved=len(citations),
                        max_score=_max_score(citations),
                        no_context=not citations,
                        status=status,
                        error=error,
                        latency_ms=_elapsed_ms(started),
                    )
                )
                await uow.commit()
        except Exception:  # noqa: BLE001 - logging is best-effort
            log.exception("request_log.write_failed")

    async def _retrieve(
        self, tenant_id: TenantId, chatbot: Chatbot, query: str
    ) -> list[Citation]:
        # Embed first (network call, no DB connection held), then open a short
        # read transaction only for the vector search.
        query_vec = await self._embedder.embed_query(query)
        async with self._uow as uow:
            uow.set_tenant_scope(tenant_id)
            hits = await uow.chunks.search(
                tenant_id=chatbot.tenant_id,
                query_embedding=query_vec,
                top_k=chatbot.retrieval.top_k,
                document_ids=chatbot.document_filter(),
                min_score=chatbot.retrieval.min_score,
            )
        return [
            Citation(
                document_id=chunk.document_id,
                chunk_id=chunk.id,
                ordinal=chunk.ordinal,
                score=score,
                snippet=chunk.text[:500],
            )
            for chunk, score in hits
        ]
