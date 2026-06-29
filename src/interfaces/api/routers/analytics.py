"""Per-chatbot answer-quality analytics.

A read-only view over persisted chat history — the 'is this chatbot working
well today vs. badly yesterday, and why?' dashboard. It computes retrieval-side
proxies (top citation score, citation count, no-context/refusal rate) plus a
provider mix, so a bad day points at retrieval vs. generation. It never touches
the answer path and never returns a score to end users — only to the operator.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, HTTPException, Query

from src.domain.shared.identifiers import ChatbotId
from src.interfaces.api.deps import ContainerDep, PrincipalDep
from src.interfaces.api.schemas import (
    AnalyticsDay,
    AnalyticsProvider,
    ChatbotAnalyticsResponse,
    RequestLogResponse,
)

_ANSWER_PREVIEW = 400

router = APIRouter(prefix="/chatbots", tags=["analytics"])


@router.get("/{chatbot_id}/analytics", response_model=ChatbotAnalyticsResponse)
async def chatbot_analytics(
    chatbot_id: uuid.UUID,
    principal: PrincipalDep,
    container: ContainerDep,
    days: int = Query(default=30, ge=1, le=180),
) -> ChatbotAnalyticsResponse:
    since = datetime.now(UTC) - timedelta(days=days)
    async with container.unit_of_work() as uow:
        uow.set_tenant_scope(principal.tenant_id)
        bot = await uow.chatbots.get(principal.tenant_id, ChatbotId(chatbot_id))
        if bot is None:
            raise HTTPException(status_code=404, detail="Chatbot not found")
        daily = await uow.analytics.chatbot_daily(
            principal.tenant_id, ChatbotId(chatbot_id), since
        )
        providers = await uow.analytics.chatbot_provider_mix(
            principal.tenant_id, ChatbotId(chatbot_id), since
        )

    return ChatbotAnalyticsResponse(
        chatbot_id=chatbot_id,
        days=days,
        daily=[
            AnalyticsDay(
                day=d.day,
                answers=d.answers,
                avg_top_score=d.avg_top_score,
                avg_citations=d.avg_citations,
                no_context_rate=d.no_context_rate,
                refusal_rate=d.refusal_rate,
                avg_tokens=d.avg_tokens,
            )
            for d in daily
        ],
        providers=[
            AnalyticsProvider(
                provider=p.provider,
                answers=p.answers,
                avg_top_score=p.avg_top_score,
                avg_tokens=p.avg_tokens,
            )
            for p in providers
        ],
    )


@router.get("/{chatbot_id}/requests", response_model=list[RequestLogResponse])
async def chatbot_requests(
    chatbot_id: uuid.UUID,
    principal: PrincipalDep,
    container: ContainerDep,
    limit: int = Query(default=50, ge=1, le=200),
) -> list[RequestLogResponse]:
    """Most recent requests for a chatbot — one row per ask, success OR failure,
    with its deterministic evaluation (retrieval strength, no-context, refusal,
    latency, provider). The per-request drill-down behind the trend charts."""
    async with container.unit_of_work() as uow:
        uow.set_tenant_scope(principal.tenant_id)
        bot = await uow.chatbots.get(principal.tenant_id, ChatbotId(chatbot_id))
        if bot is None:
            raise HTTPException(status_code=404, detail="Chatbot not found")
        logs = await uow.request_logs.list_for_chatbot(
            principal.tenant_id, ChatbotId(chatbot_id), limit
        )

    return [
        RequestLogResponse(
            id=log.id,
            created_at=log.created_at,
            query=log.query,
            status=log.status,
            num_retrieved=log.num_retrieved,
            max_score=log.max_score,
            no_context=log.no_context,
            refused=log.refused,
            provider=log.provider,
            model=log.model,
            tokens_used=log.tokens_used,
            latency_ms=log.latency_ms,
            error=log.error,
            answer=(log.answer[:_ANSWER_PREVIEW] if log.answer else None),
        )
        for log in logs
    ]
