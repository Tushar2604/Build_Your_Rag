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
from src.infrastructure.oauth.providers import OAuthBroker
from src.infrastructure.email.resend import ResendEmailSender
from src.infrastructure.llm.embeddings import GeminiEmbedder
from src.infrastructure.llm.providers import FailoverLLM, build_llm
from src.infrastructure.messaging.event_bus import InProcessEventBus
from src.infrastructure.messaging.slack import SlackSender
from src.infrastructure.messaging.twilio_whatsapp import TwilioWhatsAppSender
from src.infrastructure.messaging.webhook import WebhookSender
from src.infrastructure.messaging.whatsapp_bridge import WhatsAppBridgeClient
from src.infrastructure.observability.tracing import build_tracer
from src.infrastructure.parsing.chunker import RecursiveChunker
from src.infrastructure.parsing.parser import MultiFormatParser
from src.infrastructure.persistence.database import get_sessionmaker
from src.infrastructure.persistence.unit_of_work import SqlAlchemyUnitOfWork
from src.infrastructure.ratelimit.anon import SlidingWindowRateLimiter
from src.infrastructure.security.hashing import Argon2PasswordHasher
from src.infrastructure.security.tokens import JwtTokenService
from src.infrastructure.storage.object_storage import build_storage
from src.infrastructure.voice.elevenlabs import ElevenLabsVoiceCloner
from src.infrastructure.voice.transcription import WhisperTranscriber


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
        # Consent-based integrations (Google Calendar, Google Sheets, Cal.com).
        # Each provider reports `.enabled is False` until its OAuth app is
        # registered, and its card then renders as "not configured".
        self.oauth = OAuthBroker(settings)
        self.email = ResendEmailSender(settings)
        # Post-call delivery. The webhook signature is keyed on the JWT secret
        # so operators have one secret to rotate, not two.
        self.webhook = WebhookSender(settings.jwt_secret)
        # Outbound WhatsApp for broadcasts. Stateless — per-send Twilio
        # credentials come from the channel row, not from .env.
        self.whatsapp_sender = TwilioWhatsAppSender()
        # Slack incoming-webhook delivery. Stateless for the same reason: the
        # webhook URL comes from the tenant's integration row.
        self.slack = SlackSender()
        # Voice cloning. A no-op (`.enabled is False`) until ELEVENLABS_API_KEY
        # is set; the Clone Voice page still records and stores samples.
        self.voice_cloner = ElevenLabsVoiceCloner(settings)
        # Dictation. Rides on whichever LLM key is already set (see
        # Settings.resolve_stt); `.enabled is False` with neither, and the mic
        # button then falls back to the browser's own recogniser.
        self.transcriber = WhisperTranscriber(settings)
        # Node sidecar owning the personal-WhatsApp sockets. Disabled
        # (`.enabled is False`) until BRIDGE_TOKEN is set.
        self.whatsapp_bridge = WhatsAppBridgeClient(settings)
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
