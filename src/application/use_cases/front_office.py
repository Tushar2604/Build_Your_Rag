"""Answer a customer message as the AI receptionist.

The booking counterpart to `AskChatbot`. Both take a message on a session and
return an answer that gets persisted to the same conversation; the difference is
that this one runs the tool-using agent, so the reply can be the *result of
having booked something* rather than only words.

Shares AskChatbot's transaction discipline deliberately: no database connection
is held across the agent run, because that run makes several LLM calls and can
take tens of seconds. Holding a pooled connection for that would exhaust a
free-tier pool with a handful of concurrent conversations.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass

import structlog

from src.application.agent.tools import ToolContext
from src.application.ports.repositories import UnitOfWork
from src.domain.chat.entities import Message, MessageRole
from src.domain.chat.events import MessageAnswered
from src.domain.safety.guardrails import format_message_history, scan_input
from src.domain.shared.errors import NotFoundError, QuotaExceededError
from src.domain.shared.identifiers import ChatbotId, SessionId, TenantId

log = structlog.get_logger(__name__)

# How much of the thread the agent sees. Booking conversations are short, and
# the transcript is re-sent on every reasoning step — so this bounds cost
# quadratically, not linearly. Twenty turns is far more than any booking needs.
MAX_HISTORY_MESSAGES = 20


@dataclass(frozen=True)
class FrontOfficeAnswer:
    """What the receptionist said, and what it cost.

    Carries the stored message id so an HTTP caller can reference the reply the
    same way the retrieval path lets it — the agent persists its own answer, so
    without this the id would be unrecoverable.
    """

    answer: str
    message_id: uuid.UUID
    tokens_used: int
    provider: str


class AskFrontOffice:
    """Run the receptionist agent over one inbound message."""

    def __init__(self, uow: UnitOfWork, agent: object) -> None:
        self._uow = uow
        self._agent = agent

    async def execute(
        self,
        tenant_id: TenantId,
        session_id: SessionId,
        *,
        message: str,
        chatbot_id: ChatbotId | None = None,
        source: str = "api",
        channel: str = "",
        customer_phone: str = "",
        persist_user_message: bool = True,
    ) -> FrontOfficeAnswer:
        started = time.perf_counter()

        # --- 1. Validate, enforce quota, read history (short transaction) ---
        async with self._uow as uow:
            uow.set_tenant_scope(tenant_id)

            session = await uow.chats.get_session(tenant_id, session_id)
            if session is None:
                raise NotFoundError("Chat session not found.")
            answering_as = chatbot_id or session.chatbot_id
            if answering_as is None:
                raise NotFoundError("No assistant is attached to this conversation.")

            tenant = await uow.tenants.get(tenant_id)
            assert tenant is not None
            used = await uow.usage.tokens_used_today(tenant_id)
            if used >= tenant.daily_token_quota:
                raise QuotaExceededError("Daily token quota exceeded. Try again tomorrow.")

            prior = await uow.chats.list_messages(tenant_id, session_id)
            history = format_message_history(prior[-MAX_HISTORY_MESSAGES:])

            if persist_user_message:
                await uow.chats.add_message(
                    Message(
                        session_id=session_id,
                        tenant_id=tenant_id,
                        role=MessageRole.USER,
                        content=message,
                    )
                )
            await uow.commit()

        # The same injection screen the RAG path applies. An agent with booking
        # tools is a higher-value target than one that only reads documents, so
        # skipping it here would be the wrong way round.
        verdict = scan_input(message)
        if not verdict.allowed:
            answer = verdict.reason or "I can't help with that request."
            return await self._persist_answer(
                tenant_id, session_id, answering_as, answer, tokens=0, provider=""
            )

        # --- 2. Run the agent. No connection held. ---
        result = await self._agent.run(  # type: ignore[attr-defined]
            ToolContext(
                tenant_id=tenant_id,
                chatbot_id=answering_as,
                # What the tools need to attribute the booking and to know who
                # they are talking to without asking.
                extras={
                    "source": source,
                    "channel": channel,
                    "customer_phone": customer_phone,
                    # Scopes booking idempotency to this conversation.
                    "conversation_id": str(session_id),
                },
            ),
            message,
            history=history,
        )

        # --- 3. Persist the reply and meter it (short transaction) ---
        stored = await self._persist_answer(
            tenant_id,
            session_id,
            answering_as,
            result.answer,
            tokens=result.trace.tokens_used,
            provider=result.trace.provider or "",
        )

        log.info(
            "front_office.answered",
            tenant_id=str(tenant_id),
            source=source,
            steps=result.trace.num_steps,
            tools=",".join(result.trace.tools_used()),
            stop_reason=result.trace.stop_reason,
            latency_ms=int((time.perf_counter() - started) * 1000),
        )
        return stored

    async def _persist_answer(
        self,
        tenant_id: TenantId,
        session_id: SessionId,
        chatbot_id: ChatbotId,
        answer: str,
        *,
        tokens: int,
        provider: str,
    ) -> FrontOfficeAnswer:
        async with self._uow as uow:
            uow.set_tenant_scope(tenant_id)
            stored = Message(
                session_id=session_id,
                tenant_id=tenant_id,
                role=MessageRole.ASSISTANT,
                content=answer,
                tokens_used=tokens,
                provider=provider or None,
            )
            await uow.chats.add_message(stored)
            if tokens:
                await uow.usage.add_tokens(tenant_id, tokens)
            uow.collect_event(
                MessageAnswered(
                    tenant_id=tenant_id,
                    session_id=session_id,
                    chatbot_id=chatbot_id,
                    tokens_used=tokens,
                    provider=provider,
                )
            )
            await uow.commit()
        return FrontOfficeAnswer(
            answer=answer, message_id=stored.id, tokens_used=tokens, provider=provider
        )
