"""Gemini embeddings adapter (free tier).

Gemini's embedding endpoint is free, which is what makes ingestion cost nothing.
Calls are wrapped with retry/backoff because free tiers rate-limit aggressively.
The SDK is imported lazily so the module loads even when the key isn't set.
"""

from __future__ import annotations

import asyncio

from tenacity import retry, stop_after_attempt, wait_exponential

from src.config import Settings


class GeminiEmbedder:
    def __init__(self, settings: Settings) -> None:
        self._model = settings.embedding_model
        self._dim = settings.embedding_dim
        self._api_key = settings.gemini_api_key
        self._configured = False

    @property
    def dim(self) -> int:
        return self._dim

    def _ensure(self) -> None:
        if self._configured:
            return
        if not self._api_key:
            raise RuntimeError(
                "GEMINI_API_KEY is not set — add it to .env to enable embeddings."
            )
        import google.generativeai as genai

        genai.configure(api_key=self._api_key)
        self._genai = genai
        self._configured = True

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [await self._embed_one(t, "retrieval_document") for t in texts]

    async def embed_query(self, text: str) -> list[float]:
        return await self._embed_one(text, "retrieval_query")

    @retry(stop=stop_after_attempt(4), wait=wait_exponential(min=1, max=20))
    async def _embed_one(self, text: str, task_type: str) -> list[float]:
        self._ensure()

        def _call() -> list[float]:
            resp = self._genai.embed_content(
                model=f"models/{self._model}",
                content=text,
                task_type=task_type,
            )
            return list(resp["embedding"])

        return await asyncio.to_thread(_call)
