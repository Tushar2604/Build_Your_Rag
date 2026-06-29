"""Gemini embeddings adapter (free tier).

Calls the Gemini REST API directly with httpx to avoid SDK version churn.
The embedContent endpoint is stable on v1beta and works with text-embedding-004.
Calls are wrapped with retry/backoff because free tiers rate-limit aggressively.
"""

from __future__ import annotations

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from src.config import Settings

_BASE = "https://generativelanguage.googleapis.com/v1beta/models"


class GeminiEmbedder:
    def __init__(self, settings: Settings) -> None:
        self._model = settings.embedding_model
        self._dim = settings.embedding_dim
        self._api_key = settings.gemini_api_key

    @property
    def dim(self) -> int:
        return self._dim

    def _check_key(self) -> None:
        if not self._api_key:
            raise RuntimeError(
                "GEMINI_API_KEY is not set — add it to .env to enable embeddings."
            )

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [await self._embed_one(t, "RETRIEVAL_DOCUMENT") for t in texts]

    async def embed_query(self, text: str) -> list[float]:
        return await self._embed_one(text, "RETRIEVAL_QUERY")

    @retry(stop=stop_after_attempt(4), wait=wait_exponential(min=1, max=20))
    async def _embed_one(self, text: str, task_type: str) -> list[float]:
        self._check_key()
        url = f"{_BASE}/{self._model}:embedContent"
        payload = {
            "model": f"models/{self._model}",
            "content": {"parts": [{"text": text}]},
            "taskType": task_type,
            "outputDimensionality": self._dim,
        }
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(url, json=payload, params={"key": self._api_key})
            resp.raise_for_status()
            return resp.json()["embedding"]["values"]
