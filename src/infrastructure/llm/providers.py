"""Generation providers (Groq, Gemini, local Ollama) + a failover router.

The router is the key free-tier resilience feature: when the primary provider
rate-limits or errors, it transparently fails over to the secondary, so a user
question still gets answered. Ollama runs models locally (no API key, no quota),
which makes it a good primary for offline/private deployments or a free fallback.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable

import structlog
from tenacity import retry, stop_after_attempt, wait_exponential

from src.application.ports.services import LLMResult
from src.config import Settings

log = structlog.get_logger(__name__)


def _estimate_tokens(*parts: str) -> int:
    return max(1, sum(len(p) for p in parts) // 4)


class GroqProvider:
    name = "groq"

    def __init__(self, settings: Settings) -> None:
        self._model = settings.groq_model
        self._api_key = settings.groq_api_key
        self._client = None

    def _ensure(self):  # type: ignore[no-untyped-def]
        if self._client is None:
            from groq import AsyncGroq

            self._client = AsyncGroq(api_key=self._api_key)
        return self._client

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=10))
    async def generate(self, system: str, user: str) -> LLMResult:
        client = self._ensure()
        resp = await client.chat.completions.create(
            model=self._model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        )
        text = resp.choices[0].message.content or ""
        usage = getattr(resp, "usage", None)
        tokens = getattr(usage, "total_tokens", None) or _estimate_tokens(system, user, text)
        return LLMResult(text=text, tokens_used=tokens, provider=self.name, model=self._model)

    async def stream(
        self, system: str, user: str, on_provider: Callable[[str], None] | None = None
    ) -> AsyncIterator[str]:
        client = self._ensure()
        if on_provider:
            on_provider(self.name)
        stream = await client.chat.completions.create(
            model=self._model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            stream=True,
        )
        async for chunk in stream:
            delta = chunk.choices[0].delta.content
            if delta:
                yield delta


class GeminiProvider:
    name = "gemini"

    def __init__(self, settings: Settings) -> None:
        self._model = settings.gemini_model
        self._api_key = settings.gemini_api_key
        self._configured = False

    def _ensure(self):  # type: ignore[no-untyped-def]
        if not self._configured:
            from google import genai

            self._client = genai.Client(api_key=self._api_key)
            self._configured = True
        return self._client

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=10))
    async def generate(self, system: str, user: str) -> LLMResult:
        client = self._ensure()

        def _call() -> str:
            from google.genai import types

            response = client.models.generate_content(
                model=self._model,
                contents=user,
                config=types.GenerateContentConfig(system_instruction=system),
            )
            return response.text

        text = await asyncio.to_thread(_call)
        tokens = _estimate_tokens(system, user, text)
        return LLMResult(text=text, tokens_used=tokens, provider=self.name, model=self._model)

    async def stream(
        self, system: str, user: str, on_provider: Callable[[str], None] | None = None
    ) -> AsyncIterator[str]:
        client = self._ensure()
        if on_provider:
            on_provider(self.name)

        from google.genai import types

        def _start():  # type: ignore[no-untyped-def]
            return client.models.generate_content_stream(
                model=self._model,
                contents=user,
                config=types.GenerateContentConfig(system_instruction=system),
            )

        stream = await asyncio.to_thread(_start)
        for chunk in stream:
            if chunk.text:
                yield chunk.text


class OllamaProvider:
    """Local generation via an Ollama server (default qwen2.5).

    Talks to Ollama's OpenAI-compatible Chat Completions endpoint over httpx,
    so it needs no extra SDK. No API key and no rate limits — the only cost is
    the local box, which makes it a natural primary for private/offline setups.
    """

    name = "ollama"

    def __init__(self, settings: Settings) -> None:
        self._model = settings.ollama_model
        self._base_url = settings.ollama_base_url.rstrip("/")
        self._client = None

    def _ensure(self):  # type: ignore[no-untyped-def]
        if self._client is None:
            import httpx

            # Generous timeout: local models can be slow to load on first call.
            self._client = httpx.AsyncClient(
                base_url=f"{self._base_url}/v1", timeout=httpx.Timeout(120.0)
            )
        return self._client

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=10))
    async def generate(self, system: str, user: str) -> LLMResult:
        client = self._ensure()
        resp = await client.post(
            "/chat/completions",
            json={
                "model": self._model,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                "stream": False,
            },
        )
        resp.raise_for_status()
        data = resp.json()
        text = data["choices"][0]["message"]["content"] or ""
        usage = data.get("usage") or {}
        tokens = usage.get("total_tokens") or _estimate_tokens(system, user, text)
        return LLMResult(text=text, tokens_used=tokens, provider=self.name, model=self._model)

    async def stream(
        self, system: str, user: str, on_provider: Callable[[str], None] | None = None
    ) -> AsyncIterator[str]:
        import json

        client = self._ensure()
        if on_provider:
            on_provider(self.name)
        async with client.stream(
            "POST",
            "/chat/completions",
            json={
                "model": self._model,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                "stream": True,
            },
        ) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if not line.startswith("data: "):
                    continue
                payload = line[len("data: ") :]
                if payload.strip() == "[DONE]":
                    break
                delta = json.loads(payload)["choices"][0]["delta"].get("content")
                if delta:
                    yield delta


class FailoverLLM:
    """Tries the primary provider, falls back to the secondary on failure."""

    name = "failover"

    def __init__(self, primary, secondary) -> None:  # type: ignore[no-untyped-def]
        self._primary = primary
        self._secondary = secondary

    async def generate(self, system: str, user: str) -> LLMResult:
        try:
            return await self._primary.generate(system, user)
        except Exception:  # noqa: BLE001 - degrade to secondary free pool
            log.warning("llm.failover", primary=self._primary.name, to=self._secondary.name)
            return await self._secondary.generate(system, user)

    async def stream(
        self, system: str, user: str, on_provider: Callable[[str], None] | None = None
    ) -> AsyncIterator[str]:
        # Each leaf provider reports its own name via on_provider, so a fallback
        # overwrites the primary's report and the caller ends with the backend
        # that actually served the stream.
        try:
            async for tok in self._primary.stream(system, user, on_provider):
                yield tok
        except Exception:  # noqa: BLE001
            log.warning("llm.failover_stream", primary=self._primary.name)
            async for tok in self._secondary.stream(system, user, on_provider):
                yield tok


_PROVIDERS = {
    "groq": GroqProvider,
    "gemini": GeminiProvider,
    "ollama": OllamaProvider,
}


def _build_provider(name: str, settings: Settings):  # type: ignore[no-untyped-def]
    try:
        return _PROVIDERS[name](settings)
    except KeyError:
        raise ValueError(f"Unknown generation provider: {name!r}") from None


def build_llm(settings: Settings) -> FailoverLLM:
    primary = _build_provider(settings.generation_primary, settings)
    secondary = _build_provider(settings.generation_secondary, settings)
    return FailoverLLM(primary=primary, secondary=secondary)
