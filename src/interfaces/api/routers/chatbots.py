"""Chatbot CRUD + publish/embed configuration."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException

from src.application.use_cases.generate_assistant import (
    USE_CASE_HINTS,
    GenerateAssistantUseCase,
)
from src.config.settings import get_settings
from src.domain.chatbot.entities import (
    LANGUAGE_OPTIONS,
    LLM_MODEL_OPTIONS,
    STT_MODEL_OPTIONS,
    TTS_VOICE_OPTIONS,
    AssistantConfig,
    Chatbot,
    FlowSection,
    RetrievalConfig,
    WidgetConfig,
    default_flow_sections,
)
from src.domain.shared.identifiers import ChatbotId, DocumentId, new_id
from src.interfaces.api.deps import ContainerDep, PrincipalDep
from src.interfaces.api.schemas import (
    AssistantConfigSchema,
    AssistantKnowledgeDocument,
    AssistantKnowledgeResponse,
    AssistantOptionsResponse,
    ChatbotResponse,
    CreateChatbotRequest,
    FlowSectionSchema,
    GenerateAssistantRequest,
    RegenerateFlowRequest,
    SetAssistantKnowledgeRequest,
    UpdateChatbotRequest,
    WidgetConfigSchema,
)

router = APIRouter(prefix="/chatbots", tags=["chatbots"])

# Labels for the use-case chips under the create box. Paired with the hint text
# in `USE_CASE_HINTS` so a chip can never exist without a generator hint.
_USE_CASE_LABELS: dict[str, str] = {
    "lead_generation": "Lead Generation",
    "appointments": "Appointments",
    "support": "Support",
    "negotiation": "Negotiation",
    "collections": "Collections",
}


def embed_snippet(public_key: str) -> str:
    base = get_settings().public_widget_base
    return f'<script src="{base}/widget.js" data-chatbot-key="{public_key}" async></script>'


def public_url(public_key: str) -> str:
    return f"{get_settings().public_frontend_base}/c/{public_key}"


def _to_response(bot: Chatbot, *, ai_generated: bool = True) -> ChatbotResponse:
    return ChatbotResponse(
        id=bot.id,
        name=bot.name,
        channel=bot.channel,
        system_prompt=bot.system_prompt,
        flow_sections=[
            FlowSectionSchema(id=s.id, title=s.title, body=s.body, enabled=s.enabled)
            for s in bot.flow_sections
        ],
        voice_profile_id=bot.voice_profile_id,
        assistant=AssistantConfigSchema(
            direction=bot.assistant.direction,  # type: ignore[arg-type]
            languages=bot.assistant.languages,
            tts_voice=bot.assistant.tts_voice,
            llm_model=bot.assistant.llm_model,
            stt_model=bot.assistant.stt_model,
            welcome_message=bot.assistant.welcome_message,
            welcome_dynamic=bot.assistant.welcome_dynamic,
            welcome_interruptible=bot.assistant.welcome_interruptible,
        ),
        top_k=bot.retrieval.top_k,
        is_public=bot.is_public,
        public_key=bot.public_key,
        allowed_origins=bot.allowed_origins,
        allowed_document_ids=[uuid.UUID(str(d)) for d in bot.allowed_document_ids],
        ai_generated=ai_generated,
        widget=WidgetConfigSchema(
            theme_color=bot.widget.theme_color,
            display_name=bot.widget.display_name,
            welcome_message=bot.widget.welcome_message,
            launcher_position=bot.widget.launcher_position,  # type: ignore[arg-type]
        ),
        public_url=public_url(bot.public_key),
        embed_snippet=embed_snippet(bot.public_key),
    )


@router.get("/options", response_model=AssistantOptionsResponse)
async def assistant_options(principal: PrincipalDep) -> AssistantOptionsResponse:
    """Dropdown contents for the Assistant Settings row and the create-box chips.

    Served rather than hard-coded in the SPA so the two can't drift: every value
    the UI offers is one the domain will accept back.
    """
    return AssistantOptionsResponse(
        languages=list(LANGUAGE_OPTIONS),
        tts_voices=list(TTS_VOICE_OPTIONS),
        llm_models=list(LLM_MODEL_OPTIONS),
        stt_models=list(STT_MODEL_OPTIONS),
        use_cases=[
            {"id": key, "label": _USE_CASE_LABELS[key]}
            for key in _USE_CASE_LABELS
            if key in USE_CASE_HINTS
        ],
    )


@router.post("/generate", response_model=ChatbotResponse, status_code=201)
async def generate_chatbot(
    body: GenerateAssistantRequest, principal: PrincipalDep, container: ContainerDep
) -> ChatbotResponse:
    """Describe an assistant in prose; get a configured, saved assistant back.

    The whole assistant is created here rather than returned as a preview: the
    owner's next move is always to open it and edit, and a preview step would
    just be a modal they dismiss. Everything generated is editable afterwards,
    so nothing is lost by committing it.
    """
    blueprint = await GenerateAssistantUseCase(container.llm).execute(
        body.description, use_case=body.use_case
    )

    bot = Chatbot(
        tenant_id=principal.tenant_id,
        name=blueprint.name,
        channel=body.channel,
        retrieval=RetrievalConfig(top_k=get_settings().retrieval_top_k),
        widget=WidgetConfig(display_name=blueprint.name),
        assistant=AssistantConfig(
            direction=blueprint.direction,
            welcome_message=blueprint.welcome_message,
        ).normalized(),
    )
    bot.apply_flow_sections(blueprint.sections)

    async with container.unit_of_work() as uow:
        uow.set_tenant_scope(principal.tenant_id)
        await uow.chatbots.add(bot)
        await uow.commit()
    return _to_response(bot, ai_generated=blueprint.ai_generated)


@router.post("/{chatbot_id}/flow/generate", response_model=ChatbotResponse)
async def regenerate_flow(
    chatbot_id: uuid.UUID,
    body: RegenerateFlowRequest,
    principal: PrincipalDep,
    container: ContainerDep,
) -> ChatbotResponse:
    """"Ask AI" — rebuild an existing assistant's flow from a new description.

    Replaces the flow wholesale rather than merging: a merge would have to guess
    which of the owner's edits to keep against a freshly-authored set of
    sections, and guessing wrong silently destroys work either way. The name and
    every non-prompt setting (voice, model, knowledge, publish state) are
    preserved, so this only ever costs the prompt.
    """
    async with container.unit_of_work() as uow:
        uow.set_tenant_scope(principal.tenant_id)
        bot = await uow.chatbots.get(principal.tenant_id, ChatbotId(chatbot_id))
        if bot is None:
            raise HTTPException(status_code=404, detail="Chatbot not found")

        blueprint = await GenerateAssistantUseCase(container.llm).execute(
            body.description, use_case=body.use_case, existing_name=bot.name
        )
        bot.apply_flow_sections(blueprint.sections)
        if blueprint.welcome_message:
            bot.assistant.welcome_message = blueprint.welcome_message
            bot.assistant = bot.assistant.normalized()

        await uow.chatbots.update(bot)
        await uow.commit()
    return _to_response(bot, ai_generated=blueprint.ai_generated)


@router.post("", response_model=ChatbotResponse, status_code=201)
async def create_chatbot(
    body: CreateChatbotRequest, principal: PrincipalDep, container: ContainerDep
) -> ChatbotResponse:
    bot = Chatbot(
        tenant_id=principal.tenant_id,
        name=body.name,
        channel=body.channel,
        retrieval=RetrievalConfig(top_k=body.top_k),
        allowed_document_ids=[DocumentId(d) for d in body.allowed_document_ids],
        is_public=body.is_public,
        widget=WidgetConfig(display_name=body.name),
    )
    # A caller-supplied prompt is taken as the raw form (it has no sections to
    # show); otherwise the bot starts on the stock, editable flow.
    if body.system_prompt:
        bot.set_raw_prompt(body.system_prompt)
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
    """Edit name, prompt/flow, retrieval, publish state, embed allowlist, and
    widget appearance. Only fields present in the body are changed."""
    if body.system_prompt is not None and body.flow_sections is not None:
        raise HTTPException(
            status_code=400,
            detail="Send either system_prompt or flow_sections, not both — they are "
            "two views of the same prompt.",
        )
    async with container.unit_of_work() as uow:
        uow.set_tenant_scope(principal.tenant_id)
        bot = await uow.chatbots.get(principal.tenant_id, ChatbotId(chatbot_id))
        if bot is None:
            raise HTTPException(status_code=404, detail="Chatbot not found")

        if body.name is not None:
            bot.name = body.name
        if body.channel is not None:
            bot.channel = body.channel
        if body.system_prompt is not None:
            bot.set_raw_prompt(body.system_prompt)
        if body.flow_sections is not None:
            bot.apply_flow_sections(
                [
                    FlowSection(
                        id=s.id or new_id(), title=s.title, body=s.body, enabled=s.enabled
                    )
                    for s in body.flow_sections
                ]
            )
        if body.voice_profile_id_set:
            # Explicit opt-in so an omitted field can't silently unset the voice.
            if body.voice_profile_id is not None:
                voice = await uow.voice_profiles.get(principal.tenant_id, body.voice_profile_id)
                if voice is None:
                    raise HTTPException(status_code=404, detail="Voice not found")
                if not voice.is_usable():
                    raise HTTPException(
                        status_code=400,
                        detail="That voice isn't ready yet — finish cloning it first.",
                    )
            bot.voice_profile_id = body.voice_profile_id
        if body.assistant is not None:
            bot.assistant = AssistantConfig(
                direction=body.assistant.direction,
                languages=list(body.assistant.languages),
                tts_voice=body.assistant.tts_voice,
                llm_model=body.assistant.llm_model,
                stt_model=body.assistant.stt_model,
                welcome_message=body.assistant.welcome_message,
                welcome_dynamic=body.assistant.welcome_dynamic,
                welcome_interruptible=body.assistant.welcome_interruptible,
            ).normalized()
        if body.allowed_document_ids is not None:
            bot.allowed_document_ids = [DocumentId(d) for d in body.allowed_document_ids]
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


def _knowledge_response(bot: Chatbot, documents: list) -> AssistantKnowledgeResponse:
    attached = {str(d) for d in bot.allowed_document_ids}
    rows = [
        AssistantKnowledgeDocument(
            id=doc.id,
            filename=doc.filename,
            status=doc.status.value,
            chunk_count=doc.chunk_count,
            error=doc.error,
            attached=str(doc.id) in attached,
        )
        for doc in documents
    ]
    return AssistantKnowledgeResponse(
        documents=rows,
        attached_count=len(attached),
        ready_count=sum(1 for r in rows if r.status == "ready"),
        scope_is_all=not attached,
    )


@router.get("/{chatbot_id}/knowledge", response_model=AssistantKnowledgeResponse)
async def get_knowledge(
    chatbot_id: uuid.UUID, principal: PrincipalDep, container: ContainerDep
) -> AssistantKnowledgeResponse:
    """This assistant's knowledge base: every tenant document, flagged with
    whether this assistant may retrieve from it.

    The whole tenant list is returned, not just the attached subset, because the
    tab's job is picking — showing only what's already attached would make
    adding a source require a trip to another page.
    """
    async with container.unit_of_work() as uow:
        uow.set_tenant_scope(principal.tenant_id)
        bot = await uow.chatbots.get(principal.tenant_id, ChatbotId(chatbot_id))
        if bot is None:
            raise HTTPException(status_code=404, detail="Chatbot not found")
        documents = await uow.documents.list_for_tenant(principal.tenant_id)
    return _knowledge_response(bot, documents)


@router.put("/{chatbot_id}/knowledge", response_model=AssistantKnowledgeResponse)
async def set_knowledge(
    chatbot_id: uuid.UUID,
    body: SetAssistantKnowledgeRequest,
    principal: PrincipalDep,
    container: ContainerDep,
) -> AssistantKnowledgeResponse:
    """Replace the assistant's document set.

    Ids are intersected with the tenant's own documents before saving — an id
    from another tenant would otherwise sit in the allowlist forever, and a
    deleted document would leave a dangling reference that quietly narrows
    retrieval. An empty list means "search everything", which is the default an
    assistant starts on.
    """
    async with container.unit_of_work() as uow:
        uow.set_tenant_scope(principal.tenant_id)
        bot = await uow.chatbots.get(principal.tenant_id, ChatbotId(chatbot_id))
        if bot is None:
            raise HTTPException(status_code=404, detail="Chatbot not found")

        documents = await uow.documents.list_for_tenant(principal.tenant_id)
        owned = {str(d.id) for d in documents}
        requested = [d for d in body.document_ids if str(d) in owned]
        bot.allowed_document_ids = [DocumentId(d) for d in requested]

        await uow.chatbots.update(bot)
        await uow.commit()
    return _knowledge_response(bot, documents)


@router.post("/{chatbot_id}/flow/reset", response_model=ChatbotResponse)
async def reset_flow(
    chatbot_id: uuid.UUID, principal: PrincipalDep, container: ContainerDep
) -> ChatbotResponse:
    """Replace the prompt with the stock section set.

    Two uses: recovering a flow that was edited into a corner, and giving a bot
    authored as a raw prompt something to edit in the flow builder — which is
    why this discards the current prompt rather than trying to parse it back
    into sections (a parse would guess at boundaries and usually guess wrong).
    """
    async with container.unit_of_work() as uow:
        uow.set_tenant_scope(principal.tenant_id)
        bot = await uow.chatbots.get(principal.tenant_id, ChatbotId(chatbot_id))
        if bot is None:
            raise HTTPException(status_code=404, detail="Chatbot not found")
        bot.apply_flow_sections(default_flow_sections())
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
