"""Post-call delivery settings — CRUD per assistant, plus the two triggers that
actually fire a dispatch: closing a session, and a "send test" from the UI.

Dispatch runs as a BackgroundTask rather than inline. It makes 0-3 LLM calls
plus an outbound HTTP request; blocking the caller's response on a customer's
slow webhook would make ending a conversation feel broken.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, BackgroundTasks, HTTPException

from src.application.use_cases.post_call import DispatchPostCall
from src.config.container import get_container
from src.domain.postcall.entities import CallStatus, PostCallConfig
from src.domain.shared.identifiers import ChatbotId, SessionId, TenantId
from src.interfaces.api.deps import AdminPrincipalDep, ContainerDep, PrincipalDep
from src.interfaces.api.schemas import (
    EndSessionRequest,
    EndSessionResponse,
    PostCallConfigBody,
    PostCallConfigResponse,
    PostCallDeliveryResponse,
)

router = APIRouter(prefix="/chatbots", tags=["post-call"])


def _to_response(c: PostCallConfig) -> PostCallConfigResponse:
    return PostCallConfigResponse(
        id=c.id,
        chatbot_id=c.chatbot_id,
        delivery_method=c.delivery_method,
        webhook_url=c.webhook_url,
        email_to=c.email_to,
        trigger_statuses=c.trigger_statuses,  # type: ignore[arg-type]
        include_summary=c.include_summary,
        include_transcript=c.include_transcript,
        include_sentiment=c.include_sentiment,
        include_extracted=c.include_extracted,
        enabled=c.enabled,
        created_at=c.created_at,
    )


def _apply(config: PostCallConfig, body: PostCallConfigBody) -> None:
    config.delivery_method = body.delivery_method
    config.webhook_url = body.webhook_url.strip()
    config.email_to = body.email_to.strip()
    config.trigger_statuses = list(body.trigger_statuses)
    config.include_summary = body.include_summary
    config.include_transcript = body.include_transcript
    config.include_sentiment = body.include_sentiment
    config.include_extracted = body.include_extracted
    config.enabled = body.enabled


async def _run_dispatch(
    tenant_id: TenantId,
    chatbot_id: ChatbotId,
    session_id: SessionId,
    call_status: CallStatus,
    only_config_id: uuid.UUID | None = None,
) -> None:
    """Background entrypoint — builds its own container (no request scope)."""
    container = get_container()
    use_case = DispatchPostCall(
        container.unit_of_work(), container.llm, container.webhook, container.email
    )
    await use_case.execute(
        tenant_id,
        chatbot_id,
        session_id,
        call_status,
        only_config_id=only_config_id,
    )


# --- Configuration CRUD ---


@router.get("/{chatbot_id}/post-call", response_model=list[PostCallConfigResponse])
async def list_configs(
    chatbot_id: uuid.UUID, principal: PrincipalDep, container: ContainerDep
) -> list[PostCallConfigResponse]:
    async with container.unit_of_work() as uow:
        uow.set_tenant_scope(principal.tenant_id)
        configs = await uow.post_call_configs.list_for_chatbot(
            principal.tenant_id, ChatbotId(chatbot_id)
        )
    return [_to_response(c) for c in configs]


@router.post("/{chatbot_id}/post-call", response_model=PostCallConfigResponse, status_code=201)
async def create_config(
    chatbot_id: uuid.UUID,
    body: PostCallConfigBody,
    principal: AdminPrincipalDep,
    container: ContainerDep,
) -> PostCallConfigResponse:
    config = PostCallConfig(
        tenant_id=principal.tenant_id, chatbot_id=ChatbotId(chatbot_id)
    )
    _apply(config, body)
    if (error := config.validation_error()) is not None:
        raise HTTPException(status_code=400, detail=error)

    async with container.unit_of_work() as uow:
        uow.set_tenant_scope(principal.tenant_id)
        bot = await uow.chatbots.get(principal.tenant_id, ChatbotId(chatbot_id))
        if bot is None:
            raise HTTPException(status_code=404, detail="Chatbot not found")
        await uow.post_call_configs.add(config)
        await uow.commit()
    return _to_response(config)


@router.patch("/{chatbot_id}/post-call/{config_id}", response_model=PostCallConfigResponse)
async def update_config(
    chatbot_id: uuid.UUID,
    config_id: uuid.UUID,
    body: PostCallConfigBody,
    principal: AdminPrincipalDep,
    container: ContainerDep,
) -> PostCallConfigResponse:
    async with container.unit_of_work() as uow:
        uow.set_tenant_scope(principal.tenant_id)
        config = await uow.post_call_configs.get(principal.tenant_id, config_id)
        if config is None or config.chatbot_id != ChatbotId(chatbot_id):
            raise HTTPException(status_code=404, detail="Configuration not found")
        _apply(config, body)
        if (error := config.validation_error()) is not None:
            raise HTTPException(status_code=400, detail=error)
        await uow.post_call_configs.update(config)
        await uow.commit()
    return _to_response(config)


@router.delete("/{chatbot_id}/post-call/{config_id}", status_code=204)
async def delete_config(
    chatbot_id: uuid.UUID,
    config_id: uuid.UUID,
    principal: AdminPrincipalDep,
    container: ContainerDep,
) -> None:
    async with container.unit_of_work() as uow:
        uow.set_tenant_scope(principal.tenant_id)
        await uow.post_call_configs.delete(principal.tenant_id, config_id)
        await uow.commit()


@router.get("/{chatbot_id}/post-call-deliveries", response_model=list[PostCallDeliveryResponse])
async def list_deliveries(
    chatbot_id: uuid.UUID, principal: PrincipalDep, container: ContainerDep
) -> list[PostCallDeliveryResponse]:
    """Recent dispatch attempts. Payloads are omitted — they contain the full
    transcript, and this powers a compact status list."""
    async with container.unit_of_work() as uow:
        uow.set_tenant_scope(principal.tenant_id)
        deliveries = await uow.post_call_deliveries.list_for_chatbot(
            principal.tenant_id, ChatbotId(chatbot_id)
        )
    return [
        PostCallDeliveryResponse(
            id=d.id,
            config_id=d.config_id,
            session_id=d.session_id,
            call_status=d.call_status,  # type: ignore[arg-type]
            delivery_method=d.delivery_method,
            destination=d.destination,
            status=d.status,
            error=d.error,
            created_at=d.created_at,
        )
        for d in deliveries
    ]


# --- Triggers ---


@router.post("/{chatbot_id}/sessions/{session_id}/end", response_model=EndSessionResponse)
async def end_session(
    chatbot_id: uuid.UUID,
    session_id: uuid.UUID,
    body: EndSessionRequest,
    principal: PrincipalDep,
    container: ContainerDep,
    background: BackgroundTasks,
) -> EndSessionResponse:
    """Close a conversation and queue any matching post-call deliveries.

    Safe to call more than once: the delivery table's (config, session) unique
    constraint makes a repeat call a no-op rather than a duplicate send.
    """
    async with container.unit_of_work() as uow:
        uow.set_tenant_scope(principal.tenant_id)
        session = await uow.chats.get_session(principal.tenant_id, SessionId(session_id))
        if session is None or session.chatbot_id != ChatbotId(chatbot_id):
            raise HTTPException(status_code=404, detail="Session not found")
        configs = await uow.post_call_configs.list_for_chatbot(
            principal.tenant_id, ChatbotId(chatbot_id)
        )

    matching = [c for c in configs if c.triggers_on(body.call_status)]
    if matching:
        background.add_task(
            _run_dispatch,
            principal.tenant_id,
            ChatbotId(chatbot_id),
            SessionId(session_id),
            body.call_status,
        )
    return EndSessionResponse(
        session_id=session_id,
        call_status=body.call_status,
        dispatched=len(matching),
        skipped=len(configs) - len(matching),
    )


@router.post("/{chatbot_id}/post-call/{config_id}/test", response_model=EndSessionResponse)
async def test_config(
    chatbot_id: uuid.UUID,
    config_id: uuid.UUID,
    session_id: uuid.UUID,
    principal: AdminPrincipalDep,
    container: ContainerDep,
    background: BackgroundTasks,
) -> EndSessionResponse:
    """Fire one rule against a real past session, ignoring its trigger filter.

    Uses a real session rather than a synthetic fixture so the operator sees the
    payload their own conversations actually produce — a fabricated transcript
    would validate nothing about their prompt or their receiving system.
    """
    async with container.unit_of_work() as uow:
        uow.set_tenant_scope(principal.tenant_id)
        config = await uow.post_call_configs.get(principal.tenant_id, config_id)
        if config is None or config.chatbot_id != ChatbotId(chatbot_id):
            raise HTTPException(status_code=404, detail="Configuration not found")
        session = await uow.chats.get_session(principal.tenant_id, SessionId(session_id))
        if session is None or session.chatbot_id != ChatbotId(chatbot_id):
            raise HTTPException(
                status_code=404, detail="Pick a conversation belonging to this assistant."
            )

    background.add_task(
        _run_dispatch,
        principal.tenant_id,
        ChatbotId(chatbot_id),
        SessionId(session_id),
        "completed",
        config_id,
    )
    return EndSessionResponse(
        session_id=session_id, call_status="completed", dispatched=1, skipped=0
    )
