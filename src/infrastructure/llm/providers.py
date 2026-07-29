"""Generation providers (OpenAI, Groq, Gemini, local Ollama) + a failover router.

The router is the key resilience feature: when a provider rate-limits or errors,
it transparently fails over to the next backend in an ordered chain (by default
OpenAI -> Groq -> Gemini), so a user question still gets answered. Ollama runs
models locally (no API key, no quota), which makes it a good primary for
offline/private deployments or a free fallback.
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


# Shared across every vision-capable provider so a screenshot/scan/photo
# attachment produces real reference material, not a chatty image caption.
_IMAGE_EXTRACTION_PROMPT = (
    "Transcribe this image into plain text reference material for a knowledge "
    "base. Extract all readable text verbatim, describe any tables, charts, or "
    "diagrams factually (their structure and key values), and note any other "
    "important visual facts. Be thorough and literal — do not summarize, add "
    "commentary, or invent anything not actually visible in the image."
)


class OpenAIProvider:
    name = "openai"

    def __init__(self, settings: Settings) -> None:
        self._model = settings.openai_model
        self._api_key = settings.openai_api_key
        self._base_url = settings.openai_base_url or None
        self._client = None

    def _ensure(self):  # type: ignore[no-untyped-def]
        if self._client is None:
            from openai import AsyncOpenAI

            self._client = AsyncOpenAI(api_key=self._api_key, base_url=self._base_url)
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

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=10))
    async def describe_image(self, data: bytes, content_type: str) -> str:
        import base64

        client = self._ensure()
        b64 = base64.b64encode(data).decode("ascii")
        resp = await client.chat.completions.create(
            model=self._model,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": _IMAGE_EXTRACTION_PROMPT},
                        {"type": "image_url", "image_url": {"url": f"data:{content_type};base64,{b64}"}},
                    ],
                },
            ],
        )
        return resp.choices[0].message.content or ""


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

    async def describe_image(self, data: bytes, content_type: str) -> str:
        raise NotImplementedError("Groq does not support image extraction in this setup.")


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

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=10))
    async def describe_image(self, data: bytes, content_type: str) -> str:
        client = self._ensure()

        def _call() -> str:
            from google.genai import types

            response = client.models.generate_content(
                model=self._model,
                contents=[
                    types.Part.from_bytes(data=data, mime_type=content_type),
                    _IMAGE_EXTRACTION_PROMPT,
                ],
            )
            return response.text

        return await asyncio.to_thread(_call)


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

    async def describe_image(self, data: bytes, content_type: str) -> str:
        raise NotImplementedError(
            "Ollama vision support depends on the locally pulled model — not assumed here."
        )


class FailoverLLM:
    """Tries each provider in order, degrading to the next one on failure."""

    name = "failover"

    def __init__(self, providers) -> None:  # type: ignore[no-untyped-def]
        providers = list(providers)
        if not providers:
            raise ValueError("FailoverLLM requires at least one provider")
        self._providers = providers

    async def generate(self, system: str, user: str) -> LLMResult:
        last_exc: Exception | None = None
        for i, provider in enumerate(self._providers):
            try:
                return await provider.generate(system, user)
            except Exception as exc:  # noqa: BLE001 - degrade to the next backend
                last_exc = exc
                nxt = self._providers[i + 1].name if i + 1 < len(self._providers) else None
                log.warning("llm.failover", provider=provider.name, to=nxt)
        assert last_exc is not None  # non-empty chain guaranteed by __init__
        raise last_exc

    async def stream(
        self, system: str, user: str, on_provider: Callable[[str], None] | None = None
    ) -> AsyncIterator[str]:
        # Each leaf provider reports its own name via on_provider, so a fallback
        # overwrites the previous report and the caller ends with the backend
        # that actually served the stream.
        last_exc: Exception | None = None
        for provider in self._providers:
            try:
                async for tok in provider.stream(system, user, on_provider):
                    yield tok
                return
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
                log.warning("llm.failover_stream", provider=provider.name)
        assert last_exc is not None  # non-empty chain guaranteed by __init__
        raise last_exc

    async def describe_image(self, data: bytes, content_type: str) -> str:
        # Same try-next-provider shape as generate() — a provider that isn't
        # multimodal (Groq, Ollama here) raises NotImplementedError, which is
        # just another reason to fall through to the next one in the chain.
        last_exc: Exception | None = None
        for i, provider in enumerate(self._providers):
            try:
                return await provider.describe_image(data, content_type)
            except Exception as exc:  # noqa: BLE001 - degrade to the next backend
                last_exc = exc
                nxt = self._providers[i + 1].name if i + 1 < len(self._providers) else None
                log.warning("llm.describe_image_failover", provider=provider.name, to=nxt)
        assert last_exc is not None  # non-empty chain guaranteed by __init__
        raise last_exc


_PROVIDERS = {
    "openai": OpenAIProvider,
    "groq": GroqProvider,
    "gemini": GeminiProvider,
    "ollama": OllamaProvider,
}

# Ollama is local (no key); every other backend needs its credential configured
# or it is silently dropped from the failover chain.
_PROVIDER_KEY = {
    "openai": lambda s: bool(s.openai_api_key),
    "groq": lambda s: bool(s.groq_api_key),
    "gemini": lambda s: bool(s.gemini_api_key),
    "ollama": lambda s: True,
}


def _build_provider(name: str, settings: Settings):  # type: ignore[no-untyped-def]
    try:
        return _PROVIDERS[name](settings)
    except KeyError:
        raise ValueError(f"Unknown generation provider: {name!r}") from None


def build_llm(settings: Settings) -> FailoverLLM:
    # Ordered, de-duplicated failover chain. A stage without configured
    # credentials is skipped so the chain starts at the first usable backend.
    ordered = [
        settings.generation_primary,
        settings.generation_secondary,
        settings.generation_tertiary,
    ]
    chain: list[str] = []
    for name in ordered:
        if name and name not in chain and _PROVIDER_KEY.get(name, lambda _s: True)(settings):
            chain.append(name)
    # If nothing is configured, keep the primary so the failure is explicit at
    # call time rather than hidden behind an empty chain.
    if not chain:
        chain = [settings.generation_primary]
    return FailoverLLM([_build_provider(name, settings) for name in chain])
