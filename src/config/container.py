"""Composition root (dependency injection).

Single place where concrete adapters are constructed and wired to the ports.
Stateless singletons (embedder, llm, storage, hasher, tokens, event bus) are
built once; the UnitOfWork is created per request/use case. Nothing outside this
module imports concrete infrastructure classes — that keeps the dependency
direction pointing inward.
"""

from __future__ import annotations

from functools import lru_cache

from src.config.settings import Settings, get_settings
from src.infrastructure.agent.builder import build_agent_loop
from src.infrastructure.calendar.google import GoogleCalendarClient
from src.infrastructure.email.resend import ResendEmailSender
from src.infrastructure.llm.embeddings import GeminiEmbedder
from src.infrastructure.llm.providers import FailoverLLM, build_llm
from src.infrastructure.messaging.event_bus import InProcessEventBus
from src.infrastructure.observability.tracing import build_tracer
from src.infrastructure.parsing.chunker import RecursiveChunker
from src.infrastructure.parsing.parser import MultiFormatParser
from src.infrastructure.persistence.database import get_sessionmaker
from src.infrastructure.persistence.unit_of_work import SqlAlchemyUnitOfWork
from src.infrastructure.ratelimit.anon import SlidingWindowRateLimiter
from src.infrastructure.security.hashing import Argon2PasswordHasher
from src.infrastructure.security.tokens import JwtTokenService
from src.infrastructure.storage.object_storage import build_storage


class Container:
    """Holds process-lifetime singletons."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.event_bus = InProcessEventBus()
        # AI-observability tracer (Langfuse / OTel / both / no-op). Built before the
        # agent so the loop can be instrumented; a no-op by default.
        self.tracer = build_tracer(settings)
        self.embedder = GeminiEmbedder(settings)
        self.llm: FailoverLLM = build_llm(settings)
        self.storage = build_storage(settings)
        self.parser = MultiFormatParser()
        self.chunker = RecursiveChunker()
        self.hasher = Argon2PasswordHasher()
        self.tokens = JwtTokenService(settings)
        # Virtual Interview integrations — both are no-ops (`.enabled is False`)
        # until their settings are configured; nothing in the interview flow
        # hard-depends on either.
        self.calendar = GoogleCalendarClient(settings)
        self.email = ResendEmailSender(settings)
        # Best-effort burst guard for anonymous public-widget traffic.
        self.anon_rate_limiter = SlidingWindowRateLimiter(
            max_events=settings.public_anon_max_messages,
            window_seconds=settings.public_anon_window_seconds,
        )
        # Per-tenant burst guard for the multi-step agent endpoint (keyed by
        # tenant id in RunAgent), independent of the anonymous widget limiter.
        self.agent_rate_limiter = SlidingWindowRateLimiter(
            max_events=settings.agent_max_requests,
            window_seconds=settings.agent_window_seconds,
        )
        # Reusable multi-tool agent (registry + router + step budget) built once.
        self.agent_loop = build_agent_loop(self)
        self._sessionmaker = get_sessionmaker()

    def unit_of_work(self) -> SqlAlchemyUnitOfWork:
        """Fresh transaction boundary per use case."""
        return SqlAlchemyUnitOfWork(self._sessionmaker, self.event_bus)


@lru_cache
def get_container() -> Container:
    return Container(get_settings())
