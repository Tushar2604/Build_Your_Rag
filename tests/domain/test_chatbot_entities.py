"""Unit tests for the chatbot aggregate: RetrievalConfig, Chatbot."""

from __future__ import annotations

import uuid

from src.domain.chatbot.entities import (
    DEFAULT_SYSTEM_PROMPT,
    Chatbot,
    RetrievalConfig,
)
from src.domain.shared.identifiers import DocumentId, TenantId, new_id


# --- RetrievalConfig ---
def test_retrieval_config_defaults() -> None:
    cfg = RetrievalConfig()
    assert cfg.top_k == 5
    assert cfg.min_score == 0.0
    assert cfg.rerank is False


def test_retrieval_config_overrides() -> None:
    cfg = RetrievalConfig(top_k=10, min_score=0.3, rerank=True)
    assert cfg.top_k == 10
    assert cfg.min_score == 0.3
    assert cfg.rerank is True


# --- Chatbot ---
def test_chatbot_defaults() -> None:
    bot = Chatbot(tenant_id=TenantId(new_id()), name="Support")
    assert bot.system_prompt == DEFAULT_SYSTEM_PROMPT
    assert isinstance(bot.retrieval, RetrievalConfig)
    assert bot.retrieval.top_k == 5
    assert bot.allowed_document_ids == []
    assert bot.is_public is False
    assert isinstance(bot.id, uuid.UUID)


def test_default_system_prompt_enforces_grounding() -> None:
    # The default (recruiting) prompt grounds facts in the reference material and
    # forbids inventing company/role details.
    assert "reference material" in DEFAULT_SYSTEM_PROMPT
    assert "Do NOT invent" in DEFAULT_SYSTEM_PROMPT


def test_document_filter_empty_means_no_knowledge_not_everything() -> None:
    bot = Chatbot(tenant_id=TenantId(new_id()), name="b")
    # An assistant with no documents attached answers from its Conversational
    # Flow alone. It must NOT inherit every file another assistant uploaded —
    # returning None here would mean exactly that.
    assert bot.document_filter() == []


def test_document_filter_with_ids_returns_list() -> None:
    ids = [DocumentId(new_id()), DocumentId(new_id())]
    bot = Chatbot(tenant_id=TenantId(new_id()), name="b", allowed_document_ids=ids)
    assert bot.document_filter() == ids


def test_each_chatbot_has_independent_retrieval_config() -> None:
    a = Chatbot(tenant_id=TenantId(new_id()), name="a")
    b = Chatbot(tenant_id=TenantId(new_id()), name="b")
    a.retrieval.top_k = 99
    assert b.retrieval.top_k == 5  # default_factory, not a shared instance
