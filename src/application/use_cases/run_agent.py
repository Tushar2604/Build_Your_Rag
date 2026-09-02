"""Answer a message with the multi-step agent (vs. single-shot `AskChatbot`).

Same production guard-rails as the RAG path — tenant scope, daily token quota,
per-tenant rate limit, request logging — wrapped around the agent loop instead of
one retrieve+generate. The agent decides how many times to search and when to
answer; the use case owns the cross-cutting concerns the platform requires:

  * access control  — every tool call is tenant-scoped via `ToolContext`.
  * rate limiting    — a per-tenant sliding window guards the more expensive
                       multi-step path against abuse / runaway cost.
  * quota            — the existing daily token budget is enforced up front.
  * observability    — the full agent trace is persisted on the request log.

Citations are recovered from the trace (the `search_documents` tool returns them
as structured data) so the answer carries the same source attribution as RAG.
"""

from __future__ import annotations

import time

import structlog

from src.application.agent.loop import AgentLoop
from src.application.agent.tools import ToolContext
from src.application.dtos import AgentAnswerOutput, AgentAskInput, AgentStepOut, CitationOut
from src.application.ports.repositories import RequestLog, UnitOfWork
from src.domain.chat.entities import Message, MessageRole
from src.domain.chat.events import MessageAnswered
from src.domain.shared.errors import NotFoundError, QuotaExceededError, RateLimitedError
from src.domain.shared.identifiers import SessionId, TenantId

log = structlog.get_logger(__name__)

_REFUSAL_PREFIX = "I'm here to help with our open roles and your application"


class RunAgent:
    def __init__(self, uow: UnitOfWork, loop: AgentLoop, rate_limiter=None) -> None:
        self._uow = uow
        self._loop = loop
        self._rate_limiter = rate_limiter  # optional per-tenant burst guard

    async def execute(
        self, tenant_id: TenantId, session_id: SessionId, data: AgentAskInput
    ) -> AgentAnswerOutput:
        started = time.perf_counter()

        # --- 1. Validate scope, enforce quota + rate limit, persist user msg ---
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
            if await uow.usage.tokens_used_today(tenant_id) >= tenant.daily_token_quota:
                raise QuotaExceededError("Daily token quota exceeded. Try again tomorrow.")

            if self._rate_limiter is not None and not self._rate_limiter.allow(str(tenant_id)):
                raise RateLimitedError("Too many agent requests. Slow down and retry shortly.")

            await uow.chats.add_message(
                Message(
                    session_id=session_id,
                    tenant_id=tenant_id,
                    role=MessageRole.USER,
                    content=data.message,
                )
            )
            await uow.commit()

        # --- 2. Run the agent loop (no DB connection held across LLM/tool calls) ---
        ctx = ToolContext(
            tenant_id=tenant_id,
            chatbot_id=chatbot.id,
            extras={"allowed_document_ids": chatbot.allowed_document_ids or None},
        )
        try:
            result = await self._loop.run(ctx, data.message, tenant_prompt=chatbot.system_prompt)
        except Exception as exc:  # noqa: BLE001 - log the failed request, then surface
            await self._log_failure(tenant_id, chatbot.id, session_id, data.message, started, exc)
            raise

        trace = result.trace
        citations = _citations_from_trace(trace)
        refused = result.answer.strip().startswith(_REFUSAL_PREFIX)

        # --- 3. Persist answer + usage + request log (short txn) ---
        answer_msg = Message(
            session_id=session_id,
            tenant_id=tenant_id,
            role=MessageRole.ASSISTANT,
            content=result.answer,
            citations=[],  # agent citations live on the request log trace
            tokens_used=trace.tokens_used,
            provider=trace.provider,
        )
        async with self._uow as uow:
            uow.set_tenant_scope(tenant_id)
            await uow.chats.add_message(answer_msg)
            await uow.usage.add_tokens(tenant_id, trace.tokens_used)
            await uow.request_logs.add(
                RequestLog(
                    tenant_id=tenant_id,
                    chatbot_id=chatbot.id,
                    session_id=session_id,
                    message_id=answer_msg.id,
                    query=data.message,
                    retrieved=trace.to_dict()["steps"],  # full trace for triage
                    num_retrieved=len(citations),
                    max_score=max((c["score"] for c in citations), default=None),
                    no_context=not citations,
                    refused=refused,
                    answer=result.answer,
                    provider=trace.provider,
                    model="agent",
                    tokens_used=trace.tokens_used,
                    status="ok",
                    latency_ms=int((time.perf_counter() - started) * 1000),
                )
            )
            uow.collect_event(
                MessageAnswered(
                    tenant_id=tenant_id,
                    session_id=session_id,
                    chatbot_id=chatbot.id,
                    tokens_used=trace.tokens_used,
                    provider=trace.provider,
                )
            )
            await uow.commit()

        log.info(
            "agent.answered",
            session_id=str(session_id),
            steps=trace.num_steps,
            tools=trace.tools_used(),
            stop_reason=trace.stop_reason,
        )

        return AgentAnswerOutput(
            answer=result.answer,
            citations=[
                CitationOut(
                    document_id=c["document_id"],
                    chunk_id=c["chunk_id"],
                    ordinal=c["ordinal"],
                    score=c["score"],
                    snippet=c["snippet"],
                )
                for c in citations
            ],
            tokens_used=trace.tokens_used,
            provider=trace.provider,
            stop_reason=trace.stop_reason,
            tools_used=trace.tools_used(),
            steps=[
                AgentStepOut(
                    index=s.index,
                    thought=s.thought,
                    action=s.action,
                    observation=s.observation[:500],
                    model=s.model,
                )
                for s in trace.steps
            ],
        )

    async def _log_failure(
        self, tenant_id, chatbot_id, session_id, query, started, exc
    ) -> None:  # type: ignore[no-untyped-def]
        try:
            async with self._uow as uow:
                uow.set_tenant_scope(tenant_id)
                await uow.request_logs.add(
                    RequestLog(
                        tenant_id=tenant_id,
                        chatbot_id=chatbot_id,
                        session_id=session_id,
                        query=query,
                        status="error",
                        model="agent",
                        error=f"{type(exc).__name__}: {exc}",
                        latency_ms=int((time.perf_counter() - started) * 1000),
                    )
                )
                await uow.commit()
        except Exception:  # noqa: BLE001 - logging is best-effort
            log.exception("agent.request_log.write_failed")


def _citations_from_trace(trace) -> list[dict]:  # type: ignore[no-untyped-def]
    """De-duplicate citations gathered across every search step in a run.

    The agent may search several times; we keep the highest-scoring occurrence of
    each chunk so the answer's source list is both complete and non-repetitive.
    """
    best: dict[str, dict] = {}
    for step in trace.steps:
        for cit in step.data.get("citations", []):
            key = cit["chunk_id"]
            if key not in best or cit["score"] > best[key]["score"]:
                best[key] = cit
    return sorted(best.values(), key=lambda c: c["score"], reverse=True)
