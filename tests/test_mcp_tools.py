"""MCP tool-implementation tests with a fake container — no MCP SDK, no DB.

Exercises tenant resolution and the search/list tools against in-memory fakes,
proving the connector logic (including tenant scoping) without standing up the
protocol server or any infrastructure.
"""

from __future__ import annotations

import uuid

import pytest
from src.infrastructure.security.hashing import hash_api_key
from src.interfaces.mcp.tools import (
    McpAuth,
    McpAuthError,
    list_documents,
    resolve_tenant,
    search_documents,
)


# --- Fakes -----------------------------------------------------------------------
class _Chunk:
    def __init__(self, doc_id, chunk_id, ordinal, text) -> None:
        self.document_id = doc_id
        self.id = chunk_id
        self.ordinal = ordinal
        self.text = text


class _Doc:
    def __init__(self, id, filename, status, chunk_count, error=None) -> None:
        self.id = id
        self.filename = filename
        self.status = status
        self.chunk_count = chunk_count
        self.error = error


class _ApiKey:
    def __init__(self, tenant_id) -> None:
        self.tenant_id = tenant_id


class _Repos:
    def __init__(self, *, hits=None, docs=None, api_keys=None) -> None:
        self._hits = hits or []
        self._docs = docs or []
        self._api_keys = api_keys or {}
        self.scoped_tenant = None

    # chunks
    async def search(self, **kwargs):
        return self._hits

    # documents
    async def list_for_tenant(self, tenant_id):
        return self._docs

    # api_keys
    async def get_by_hash(self, key_hash):
        return self._api_keys.get(key_hash)


class _UoW:
    def __init__(self, repos: _Repos) -> None:
        self.chunks = repos
        self.documents = repos
        self.api_keys = repos
        self._repos = repos

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return None

    def set_tenant_scope(self, tenant_id):
        self._repos.scoped_tenant = tenant_id


class _Embedder:
    async def embed_query(self, text):
        return [0.0, 1.0, 0.0]


class _Container:
    def __init__(self, repos: _Repos) -> None:
        self._repos = repos
        self.embedder = _Embedder()

    def unit_of_work(self):
        return _UoW(self._repos)


# --- Tests -----------------------------------------------------------------------
@pytest.mark.asyncio
async def test_resolve_tenant_success() -> None:
    tenant_id = uuid.uuid4()
    key = "sk_secret"
    repos = _Repos(api_keys={hash_api_key(key): _ApiKey(tenant_id)})
    auth = await resolve_tenant(_Container(repos), key)
    assert auth.tenant_id == tenant_id


@pytest.mark.asyncio
async def test_resolve_tenant_rejects_blank_and_unknown() -> None:
    repos = _Repos(api_keys={})
    with pytest.raises(McpAuthError):
        await resolve_tenant(_Container(repos), "")
    with pytest.raises(McpAuthError):
        await resolve_tenant(_Container(repos), "sk_unknown")


@pytest.mark.asyncio
async def test_search_documents_scopes_tenant_and_shapes_results() -> None:
    tenant_id = uuid.uuid4()
    doc_id = uuid.uuid4()
    repos = _Repos(hits=[(_Chunk(doc_id, "c1", 0, "Refunds within 30 days."), 0.88)])
    result = await search_documents(_Container(repos), McpAuth(tenant_id=tenant_id), "refund", 5)

    assert repos.scoped_tenant == tenant_id  # tenant isolation enforced
    assert result["results"][0]["score"] == 0.88
    assert result["results"][0]["document_id"] == str(doc_id)


@pytest.mark.asyncio
async def test_search_documents_empty_query_short_circuits() -> None:
    repos = _Repos()
    result = await search_documents(_Container(repos), McpAuth(tenant_id=uuid.uuid4()), "  ", 5)
    assert result["results"] == []


@pytest.mark.asyncio
async def test_search_clamps_top_k() -> None:
    # top_k is clamped to [1, 20]; assert it does not raise and returns shape.
    repos = _Repos(hits=[])
    out = await search_documents(_Container(repos), McpAuth(tenant_id=uuid.uuid4()), "q", 999)
    assert out["results"] == []


@pytest.mark.asyncio
async def test_list_documents_reports_status() -> None:
    tenant_id = uuid.uuid4()
    docs = [
        _Doc(uuid.uuid4(), "a.pdf", "ready", 12),
        _Doc(uuid.uuid4(), "b.docx", "failed", 0, "boom"),
    ]
    repos = _Repos(docs=docs)
    result = await list_documents(_Container(repos), McpAuth(tenant_id=tenant_id))

    assert repos.scoped_tenant == tenant_id
    assert result["count"] == 2
    assert result["documents"][1]["error"] == "boom"
