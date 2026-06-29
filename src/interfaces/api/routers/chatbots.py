"""Chatbot CRUD + publish/embed configuration."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException

from src.config.settings import get_settings
from src.domain.chatbot.entities import (
    DEFAULT_SYSTEM_PROMPT,
    Chatbot,
    RetrievalConfig,
    WidgetConfig,
)
from src.domain.shared.identifiers import ChatbotId, DocumentId
from src.interfaces.api.deps import ContainerDep, PrincipalDep
from src.interfaces.api.schemas import (
    ChatbotResponse,
    CreateChatbotRequest,
    UpdateChatbotRequest,
    WidgetConfigSchema,
)

router = APIRouter(prefix="/chatbots", tags=["chatbots"])


def embed_snippet(public_key: str) -> str:
    base = get_settings().public_widget_base
    return f'<script src="{base}/widget.js" data-chatbot-key="{public_key}" async></script>'


def public_url(public_key: str) -> str:
    return f"{get_settings().public_frontend_base}/c/{public_key}"


def _to_response(bot: Chatbot) -> ChatbotResponse:
    return ChatbotResponse(
        id=bot.id,
        name=bot.name,
        system_prompt=bot.system_prompt,
        top_k=bot.retrieval.top_k,
        is_public=bot.is_public,
        public_key=bot.public_key,
        allowed_origins=bot.allowed_origins,
        widget=WidgetConfigSchema(
            theme_color=bot.widget.theme_color,
            display_name=bot.widget.display_name,
            welcome_message=bot.widget.welcome_message,
            launcher_position=bot.widget.launcher_position,  # type: ignore[arg-type]
        ),
        public_url=public_url(bot.public_key),
        embed_snippet=embed_snippet(bot.public_key),
    )


@router.post("", response_model=ChatbotResponse, status_code=201)
async def create_chatbot(
    body: CreateChatbotRequest, principal: PrincipalDep, container: ContainerDep
) -> ChatbotResponse:
    bot = Chatbot(
        tenant_id=principal.tenant_id,
        name=body.name,
        system_prompt=body.system_prompt or DEFAULT_SYSTEM_PROMPT,
        retrieval=RetrievalConfig(top_k=body.top_k),
        allowed_document_ids=[DocumentId(d) for d in body.allowed_document_ids],
        is_public=body.is_public,
        widget=WidgetConfig(display_name=body.name),
    )
    async with container.unit_of_work() as uow:
        uow.set_tenant_scope(principal.tenant_id)
        await uow.chatbots.add(bot)
        await uow.commit()
    return _to_response(bot)


@router.get("", response_model=list[ChatbotResponse])
async def list_chatbots(
    principal: PrincipalDep, container: ContainerDep
) -> list[ChatbotResponse]:
    async with container.unit_of_work() as uow:
        uow.set_tenant_scope(principal.tenant_id)
        bots = await uow.chatbots.list_for_tenant(principal.tenant_id)
    return [_to_response(b) for b in bots]


@router.get("/{chatbot_id}", response_model=ChatbotResponse)
async def get_chatbot(
    chatbot_id: uuid.UUID, principal: PrincipalDep, container: ContainerDep
) -> ChatbotResponse:
    async with container.unit_of_work() as uow:
        uow.set_tenant_scope(principal.tenant_id)
        bot = await uow.chatbots.get(principal.tenant_id, ChatbotId(chatbot_id))
    if bot is None:
        raise HTTPException(status_code=404, detail="Chatbot not found")
    return _to_response(bot)


@router.patch("/{chatbot_id}", response_model=ChatbotResponse)
async def update_chatbot(
    chatbot_id: uuid.UUID,
    body: UpdateChatbotRequest,
    principal: PrincipalDep,
    container: ContainerDep,
) -> ChatbotResponse:
    """Edit name, prompt, retrieval, publish state, embed allowlist, and widget
    appearance. Only fields present in the body are changed."""
    async with container.unit_of_work() as uow:
        uow.set_tenant_scope(principal.tenant_id)
        bot = await uow.chatbots.get(principal.tenant_id, ChatbotId(chatbot_id))
        if bot is None:
            raise HTTPException(status_code=404, detail="Chatbot not found")

        if body.name is not None:
            bot.name = body.name
        if body.system_prompt is not None:
            bot.system_prompt = body.system_prompt
        if body.top_k is not None:
            bot.retrieval.top_k = body.top_k
        if body.is_public is not None:
            bot.is_public = body.is_public
        if body.allowed_origins is not None:
            bot.allowed_origins = [o.strip() for o in body.allowed_origins if o.strip()]
        if body.widget is not None:
            bot.widget = WidgetConfig(
                theme_color=body.widget.theme_color,
                display_name=body.widget.display_name,
                welcome_message=body.widget.welcome_message,
                launcher_position=body.widget.launcher_position,
            ).normalized()

        await uow.chatbots.update(bot)
        await uow.commit()
    return _to_response(bot)


@router.post("/{chatbot_id}/rotate-key", response_model=ChatbotResponse)
async def rotate_key(
    chatbot_id: uuid.UUID, principal: PrincipalDep, container: ContainerDep
) -> ChatbotResponse:
    """Issue a fresh publishable key. Any snippet already deployed with the old
    key stops working — use this if a key leaks or is abused."""
    async with container.unit_of_work() as uow:
        uow.set_tenant_scope(principal.tenant_id)
        bot = await uow.chatbots.get(principal.tenant_id, ChatbotId(chatbot_id))
        if bot is None:
            raise HTTPException(status_code=404, detail="Chatbot not found")
        bot.rotate_public_key()
        await uow.chatbots.update(bot)
        await uow.commit()
    return _to_response(bot)
