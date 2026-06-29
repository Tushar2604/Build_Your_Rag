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
    # The default prompt instructs context-only answering + citation.
    assert "ONLY the provided context" in DEFAULT_SYSTEM_PROMPT
    assert "Cite sources" in DEFAULT_SYSTEM_PROMPT


def test_document_filter_empty_returns_none() -> None:
    bot = Chatbot(tenant_id=TenantId(new_id()), name="b")
    # Empty allow-list means "search all tenant documents".
    assert bot.document_filter() is None


def test_document_filter_with_ids_returns_list() -> None:
    ids = [DocumentId(new_id()), DocumentId(new_id())]
    bot = Chatbot(tenant_id=TenantId(new_id()), name="b", allowed_document_ids=ids)
    assert bot.document_filter() == ids


def test_each_chatbot_has_independent_retrieval_config() -> None:
    a = Chatbot(tenant_id=TenantId(new_id()), name="a")
    b = Chatbot(tenant_id=TenantId(new_id()), name="b")
    a.retrieval.top_k = 99
    assert b.retrieval.top_k == 5  # default_factory, not a shared instance
