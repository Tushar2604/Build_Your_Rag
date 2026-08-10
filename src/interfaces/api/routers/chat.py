"""Chat endpoints: create session, ask (JSON), and ask (SSE stream)."""

from __future__ import annotations

import json
import time
import uuid

import structlog
from fastapi import APIRouter, HTTPException
from sse_starlette.sse import EventSourceResponse

from src.application.dtos import AskInput
from src.application.ports.repositories import RequestLog
from src.application.use_cases.ask_chatbot import AskChatbot
from src.domain.chat.entities import ChatSession, Message, MessageRole
from src.domain.chatbot.entities import opener_instruction, static_welcome
from src.domain.safety.guardrails import (
    GUARD_REFUSAL,
    build_grounded_prompt,
    format_message_history,
    scan_input,
    scan_output,
)
from src.domain.shared.errors import QuotaExceededError
from src.domain.shared.identifiers import ChatbotId, SessionId
from src.infrastructure.rag.graph import RagGraph, build_context

log = structlog.get_logger(__name__)
from src.interfaces.api.deps import ContainerDep, PrincipalDep
from src.interfaces.api.schemas import (
    AnswerResponse,
    AskRequest,
    CitationResponse,
    CreateSessionResponse,
)

router = APIRouter(tags=["chat"])


@router.post(
    "/chatbots/{chatbot_id}/sessions",
    response_model=CreateSessionResponse,
    status_code=201,
)
async def create_session(
    chatbot_id: uuid.UUID, principal: PrincipalDep, container: ContainerDep
) -> CreateSessionResponse:
    async with container.unit_of_work() as uow:
        uow.set_tenant_scope(principal.tenant_id)
        bot = await uow.chatbots.get(principal.tenant_id, ChatbotId(chatbot_id))
        if bot is None:
            raise HTTPException(status_code=404, detail="Chatbot not found")
        session = ChatSession(tenant_id=principal.tenant_id, chatbot_id=bot.id)
        await uow.chats.add_session(session)
        await uow.commit()
    return CreateSessionResponse(session_id=session.id)


@router.post("/sessions/{session_id}/messages", response_model=AnswerResponse)
async def ask(
    session_id: uuid.UUID,
    body: AskRequest,
    principal: PrincipalDep,
    container: ContainerDep,
) -> AnswerResponse:
    use_case = AskChatbot(container.unit_of_work(), container.embedder, container.llm)
    result = await use_case.execute(
        principal.tenant_id, SessionId(session_id), AskInput(message=body.message)
    )
    return AnswerResponse(
        message_id=result.message_id,
        answer=result.answer,
        citations=[
            CitationResponse(
                document_id=c.document_id, ordinal=c.ordinal,
                score=c.score, snippet=c.snippet,
            )
            for c in result.citations
        ],
        tokens_used=result.tokens_used,
        provider=result.provider,
    )


@router.post("/sessions/{session_id}/stream")
async def ask_stream(
    session_id: uuid.UUID,
    body: AskRequest,
    principal: PrincipalDep,
    container: ContainerDep,
) -> EventSourceResponse:
    """Token-by-token SSE. Retrieval runs first (citations sent up front), then
    generation streams; the full message + usage are persisted at the end."""

    started = time.perf_counter()

    # Load context within a short-lived transaction up front.
    async with container.unit_of_work() as uow:
        uow.set_tenant_scope(principal.tenant_id)
        session = await uow.chats.get_session(principal.tenant_id, SessionId(session_id))
        if session is None:
            raise HTTPException(status_code=404, detail="Session not found")
        bot = await uow.chatbots.get(principal.tenant_id, session.chatbot_id)
        if bot is None:
            raise HTTPException(status_code=404, detail="Chatbot not found")
        tenant = await uow.tenants.get(principal.tenant_id)
        used = await uow.usage.tokens_used_today(principal.tenant_id)
        if tenant and used >= tenant.daily_token_quota:
            raise QuotaExceededError("Daily token quota exceeded.")
        # Fetched BEFORE the current message is added, so it reflects prior
        # turns only — without this, every turn was generated with no memory
        # of the conversation so far, which is why the assistant could re-ask
        # something the visitor already answered.
        history_text = format_message_history(
            await uow.chats.list_messages(principal.tenant_id, SessionId(session_id))
        )
        await uow.chats.add_message(
            Message(
                session_id=SessionId(session_id),
                tenant_id=principal.tenant_id,
                role=MessageRole.USER,
                content=body.message,
            )
        )
        await uow.commit()

    # Input guardrail: screen for prompt injection BEFORE retrieval/generation.
    # A high-risk message skips retrieval entirely (no embed call, no leaking
    # which documents matched) and streams a single refusal.
    input_verdict = scan_input(body.message)

    # Retrieval is read-only, so it runs through a proxy that opens its own
    # short transaction rather than holding one open for the whole stream.
    if input_verdict.allowed:
        graph = RagGraph(_ChunkRepoProxy(container), container.embedder, container.llm)
        citations = await graph.retrieve_only(bot, body.message)
        context = build_context(citations)
    else:
        log.warning("guardrail.input_blocked", categories=input_verdict.categories)
        citations = []
        context = ""

    # Retrieval trace, fixed for this request — reused by the request log below.
    retrieved_payload = [
        {
            "chunk_id": c.chunk_id,
            "document_id": str(c.document_id),
            "ordinal": c.ordinal,
            "score": c.score,
        }
        for c in citations
    ]
    max_score = max((c.score for c in citations), default=None)

    async def _log(**fields) -> None:  # type: ignore[no-untyped-def]
        """Write a request log in its own txn; best-effort, never raises."""
        try:
            async with container.unit_of_work() as uow:
                uow.set_tenant_scope(principal.tenant_id)
                await uow.request_logs.add(
                    RequestLog(
                        tenant_id=principal.tenant_id,
                        chatbot_id=bot.id,
                        session_id=SessionId(session_id),
                        query=body.message,
                        retrieved=retrieved_payload,
                        num_retrieved=len(citations),
                        max_score=max_score,
                        no_context=not citations,
                        latency_ms=int((time.perf_counter() - started) * 1000),
                        **fields,
                    )
                )
                await uow.commit()
        except Exception:  # noqa: BLE001 - logging is best-effort
            pass

    async def event_generator():  # type: ignore[no-untyped-def]
        # 1. citations event
        yield {
            "event": "citations",
            "data": json.dumps(
                [
                    {
                        "document_id": str(c.document_id),
                        "ordinal": c.ordinal,
                        "score": c.score,
                        "snippet": c.snippet,
                    }
                    for c in citations
                ]
            ),
        }
        # 2. stream tokens. Capture which backend actually served (failover-aware)
        # so the persisted answer carries an accurate provider for analytics.
        # Untrusted text is isolated in labelled blocks (build_grounded_prompt).
        prompt = (
            "" if not input_verdict.allowed
            else build_grounded_prompt(context, body.message, history=history_text)
        )
        full: list[str] = []
        served_by: dict[str, str] = {}
        if not input_verdict.allowed:
            # Blocked input: stream the refusal instead of calling the model.
            served_by["provider"] = "guardrail"
            full.append(GUARD_REFUSAL)
            yield {"event": "token", "data": GUARD_REFUSAL}
        else:
            try:
                async for token in container.llm.stream(
                    bot.system_prompt, prompt, on_provider=lambda name: served_by.__setitem__("provider", name)
                ):
                    full.append(token)
                    yield {"event": "token", "data": token}
            except Exception as exc:  # noqa: BLE001 - log the failed request, then end the stream
                await _log(
                    status="error",
                    error=f"{type(exc).__name__}: {exc}",
                    provider=served_by.get("provider"),
                )
                yield {"event": "error", "data": json.dumps({"detail": "Generation failed."})}
                return

        answer_text = "".join(full)
        tokens_used = max(1, (len(bot.system_prompt) + len(prompt) + len(answer_text)) // 4)
        refused = not input_verdict.allowed or answer_text.strip().startswith(
            "I'm here to help with our open roles and your application"
        )
        # Output guardrail. Tokens are already streamed, so on a leak we can't
        # un-send — we flag it on the request log for triage and mark it refused.
        if input_verdict.allowed:
            output_verdict = scan_output(answer_text, system_prompt=bot.system_prompt)
            if not output_verdict.allowed:
                log.warning("guardrail.output_flagged", categories=output_verdict.categories)
                refused = True

        # 3. persist assistant message + usage + request log
        assistant = Message(
            session_id=SessionId(session_id),
            tenant_id=principal.tenant_id,
            role=MessageRole.ASSISTANT,
            content=answer_text,
            citations=citations,
            tokens_used=tokens_used,
            provider=served_by.get("provider"),
        )
        async with container.unit_of_work() as uow:
            uow.set_tenant_scope(principal.tenant_id)
            await uow.chats.add_message(assistant)
            await uow.usage.add_tokens(principal.tenant_id, tokens_used)
            await uow.commit()

        await _log(
            status="ok",
            message_id=assistant.id,
            answer=answer_text,
            refused=refused,
            provider=served_by.get("provider"),
            tokens_used=tokens_used,
        )

        yield {"event": "done", "data": json.dumps({"tokens_used": tokens_used})}

    return EventSourceResponse(event_generator())


@router.post("/sessions/{session_id}/greeting")
async def greet(
    session_id: uuid.UUID,
    principal: PrincipalDep,
    container: ContainerDep,
) -> EventSourceResponse:
    """AI-generated opening turn for a brand-new session — same SSE contract as
    /stream (citations -> token* -> done) but with no user input: the model
    greets the visitor and asks what they're here for, grounded in the chatbot's
    own system prompt. Only valid once, before any other message exists."""

    started = time.perf_counter()

    async with container.unit_of_work() as uow:
        uow.set_tenant_scope(principal.tenant_id)
        session = await uow.chats.get_session(principal.tenant_id, SessionId(session_id))
        if session is None:
            raise HTTPException(status_code=404, detail="Session not found")
        bot = await uow.chatbots.get(principal.tenant_id, session.chatbot_id)
        if bot is None:
            raise HTTPException(status_code=404, detail="Chatbot not found")
        existing = await uow.chats.list_messages(principal.tenant_id, SessionId(session_id))
        if existing:
            raise HTTPException(status_code=400, detail="Session already started")
        tenant = await uow.tenants.get(principal.tenant_id)
        used = await uow.usage.tokens_used_today(principal.tenant_id)
        if tenant and used >= tenant.daily_token_quota:
            raise QuotaExceededError("Daily token quota exceeded.")

    # With Dynamic off the operator wants their exact words — no model call.
    verbatim = static_welcome(bot.assistant)
    instruction = opener_instruction(bot.assistant)

    async def event_generator():  # type: ignore[no-untyped-def]
        yield {"event": "citations", "data": "[]"}
        full: list[str] = []
        served_by: dict[str, str] = {}
        if verbatim is not None:
            full.append(verbatim)
            yield {"event": "token", "data": verbatim}
        else:
            try:
                async for token in container.llm.stream(
                    bot.system_prompt,
                    instruction,
                    on_provider=lambda name: served_by.__setitem__("provider", name),
                ):
                    full.append(token)
                    yield {"event": "token", "data": token}
            except Exception as exc:  # noqa: BLE001 - log then end the stream
                log.warning("greeting.generation_failed", error=str(exc))
                yield {"event": "error", "data": json.dumps({"detail": "Generation failed."})}
                return

        answer_text = "".join(full)
        tokens_used = (
            0
            if verbatim is not None
            else max(1, (len(bot.system_prompt) + len(instruction) + len(answer_text)) // 4)
        )

        assistant = Message(
            session_id=SessionId(session_id),
            tenant_id=principal.tenant_id,
            role=MessageRole.ASSISTANT,
            content=answer_text,
            tokens_used=tokens_used,
            provider=served_by.get("provider"),
        )
        async with container.unit_of_work() as uow:
            uow.set_tenant_scope(principal.tenant_id)
            await uow.chats.add_message(assistant)
            await uow.usage.add_tokens(principal.tenant_id, tokens_used)
            try:
                await uow.request_logs.add(
                    RequestLog(
                        tenant_id=principal.tenant_id,
                        chatbot_id=bot.id,
                        session_id=SessionId(session_id),
                        message_id=assistant.id,
                        query="(session start)",
                        answer=answer_text,
                        status="ok",
                        provider=served_by.get("provider"),
                        tokens_used=tokens_used,
                        latency_ms=int((time.perf_counter() - started) * 1000),
                    )
                )
            except Exception:  # noqa: BLE001 - logging is best-effort
                pass
            await uow.commit()

        yield {"event": "done", "data": json.dumps({"tokens_used": tokens_used})}

    return EventSourceResponse(event_generator())


class _ChunkRepoProxy:
    """Adapts the container so RagGraph can run a vector search outside a UoW
    transaction (read-only retrieval for the streaming path)."""

    def __init__(self, container: ContainerDep) -> None:
        self._container = container

    async def search(self, **kwargs):  # type: ignore[no-untyped-def]
        async with self._container.unit_of_work() as uow:
            uow.set_tenant_scope(kwargs["tenant_id"])
            return await uow.chunks.search(**kwargs)
