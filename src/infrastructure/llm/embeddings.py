"""Gemini embeddings adapter (free tier).

Calls the Gemini REST API directly with httpx to avoid SDK version churn.
The embedContent endpoint is stable on v1beta and works with text-embedding-004.
Calls are wrapped with retry/backoff because free tiers rate-limit aggressively.

Two concurrency properties matter here, because an embedding runs on *every*
retrieval and is therefore the busiest external call in the chat path:

  * the HTTP connection pool is shared process-wide rather than rebuilt per
    call, so a burst of simultaneous chats reuses warm TLS connections;
  * concurrent calls are capped by a bulkhead, so ingesting a large document
    cannot exhaust the same free-tier quota the live chatbots are using.
"""

from __future__ import annotations

import asyncio

from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

from src.config import Settings
from src.infrastructure.http_client import get_client
from src.infrastructure.llm.resilience import Bulkhead, is_rate_limited, is_transient

_BASE = "https://generativelanguage.googleapis.com/v1beta/models"


def _retryable(exc: BaseException) -> bool:
    """Embeddings have no failover chain to route to, so unlike generation a
    rate limit here IS worth waiting out — there is nowhere else to go. The
    bulkhead is what keeps us from provoking it in the first place."""
    return is_transient(exc) or is_rate_limited(exc)


class GeminiEmbedder:
    def __init__(self, settings: Settings) -> None:
        self._model = settings.embedding_model
        self._dim = settings.embedding_dim
        self._api_key = settings.gemini_api_key
        self._bulkhead = Bulkhead(settings.embedding_max_concurrency)

    @property
    def dim(self) -> int:
        return self._dim

    def _check_key(self) -> None:
        if not self._api_key:
            raise RuntimeError(
                "GEMINI_API_KEY is not set — add it to .env to enable embeddings."
            )

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """Embed a batch concurrently, bounded by the bulkhead.

        This used to be a sequential comprehension, which made ingesting a
        document an O(chunks) chain of round trips — minutes for a large file,
        during which the request held a database connection. Gathering lets the
        bulkhead decide the real parallelism; ordering is preserved because
        `asyncio.gather` returns results positionally, and callers zip these
        back onto their chunks.
        """
        if not texts:
            return []
        return list(
            await asyncio.gather(
                *(self._embed_one(t, "RETRIEVAL_DOCUMENT") for t in texts)
            )
        )

    async def embed_query(self, text: str) -> list[float]:
        return await self._embed_one(text, "RETRIEVAL_QUERY")

    @retry(
        retry=retry_if_exception(_retryable),
        stop=stop_after_attempt(4),
        wait=wait_exponential(min=1, max=20),
        reraise=True,
    )
    async def _embed_one(self, text: str, task_type: str) -> list[float]:
        self._check_key()
        url = f"{_BASE}/{self._model}:embedContent"
        payload = {
            "model": f"models/{self._model}",
            "content": {"parts": [{"text": text}]},
            "taskType": task_type,
            "outputDimensionality": self._dim,
        }
        client = await get_client("gemini-embed", timeout=30)
        async with self._bulkhead():
            resp = await client.post(url, json=payload, params={"key": self._api_key})
            resp.raise_for_status()
            return resp.json()["embedding"]["values"]
