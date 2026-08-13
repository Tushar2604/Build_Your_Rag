"""Application configuration.

All settings load from environment variables (or a local `.env`). This is the
single source of truth for runtime config — nothing else in the codebase reads
`os.environ` directly. See `.env.example` for documentation of each value.
"""

from __future__ import annotations

import ssl
from functools import lru_cache
from typing import Literal
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from pydantic import PostgresDsn, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Placeholder secrets that must never be used in production.
_INSECURE_JWT_SECRETS = {"", "change-me", "change-me-please-use-a-long-random-string"}

# Query params understood by libpq/psycopg but NOT by asyncpg. Managed Postgres
# (Neon, Supabase, Render) append these to their connection strings; passed to
# asyncpg they raise `connect() got an unexpected keyword argument 'sslmode'`.
# We strip them from the DSN and re-apply TLS via connect_args instead.
_LIBPQ_ONLY_PARAMS = {
    "sslmode",
    "channel_binding",
    "target_session_attrs",
    "gssencmode",
    "options",
}
_HOSTS_WITHOUT_TLS = {"localhost", "127.0.0.1", "::1", "db"}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # --- App ---
    app_env: Literal["development", "production"] = "development"
    app_debug: bool = True
    app_base_url: str = "http://localhost:8000"
    log_level: str = "INFO"

    # --- Security ---
    jwt_secret: str = "change-me"
    jwt_access_ttl_minutes: int = 30
    jwt_refresh_ttl_days: int = 14
    jwt_algorithm: str = "HS256"
    # How long a password-reset link stays usable. Short by design: the link
    # lives in an inbox, and the token is single-use only because it is tied to
    # the password hash it was issued against.
    password_reset_ttl_minutes: int = 30

    # --- Database ---
    database_url: str = "postgresql+asyncpg://rag:rag@localhost:5432/rag"
    # Verify the database server's TLS certificate chain. Off by default because
    # managed providers disagree: Supabase's pooler is self-signed and refusing
    # it stops the app booting, while Neon's chain is publicly trusted. Turn on
    # where the provider supports it.
    database_ssl_verify: bool = False

    # --- LLM providers ---
    openai_api_key: str = ""
    gemini_api_key: str = ""
    groq_api_key: str = ""
    embedding_model: str = "gemini-embedding-001"
    embedding_dim: int = 768
    # Generation backends form an ordered failover chain: `primary` serves first,
    # then `secondary`, then `tertiary`. On each failure the router drops to the
    # next backend. Any stage whose API key is unset is skipped automatically, so
    # a missing OPENAI_API_KEY simply starts the chain at Groq. Set every stage to
    # "ollama" for a fully local, key-free setup.
    generation_primary: Literal["openai", "groq", "gemini", "ollama"] = "openai"
    generation_secondary: Literal["openai", "groq", "gemini", "ollama"] = "groq"
    generation_tertiary: Literal["openai", "groq", "gemini", "ollama"] = "gemini"
    openai_model: str = "gpt-4o-mini"
    # Optional override for an OpenAI-compatible gateway (Azure, OpenRouter, etc.).
    openai_base_url: str = ""
    groq_model: str = "llama-3.3-70b-versatile"
    gemini_model: str = "gemini-2.5-flash"
    # Local Ollama (https://ollama.com). Run `ollama pull qwen2.5` first.
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "qwen2.5"
    # Sampling temperature for every generation backend. Low on purpose: these
    # are grounded, retrieval-backed answers, and the providers' own default of
    # 1.0 is tuned for creative writing — it is what makes a bot paraphrase its
    # sources into details they never contained. Raise it only if replies start
    # reading as stilted.
    llm_temperature: float = 0.2
    # Platform-wide relevance floor for retrieval, as cosine similarity.
    # `top_k` alone always returns its k best chunks however bad they are, so an
    # off-topic question still arrives at the model dressed as reference
    # material — a large part of why answers come back confidently wrong. An
    # assistant that sets its own higher `min_score` keeps it; this is the floor
    # under the ones that never did.
    #
    # Kept low on purpose. `gemini-embedding-001` cosine scores rarely clear
    # 0.65, and a floor near that empties the context for almost every query
    # (which a previous change learned the hard way — see the note in
    # `RagGraph._assemble`). The heavier lifting is done by the relative floor
    # in `domain.chat.relevance`, which is scale-free; this only cuts noise.
    retrieval_min_score_floor: float = 0.15

    # --- Object storage ---
    r2_endpoint_url: str = ""
    r2_access_key_id: str = ""
    r2_secret_access_key: str = ""
    r2_bucket: str = "rag-uploads"
    local_storage_dir: str = "/tmp/uploads"

    # --- CORS ---
    cors_origins: list[str] = ["*"]

    # --- Public widget / embedding ---
    # Base URL that serves the widget script + public API (where third-party
    # pages load /widget.js and call /api/v1/public/*). Falls back to app_base_url.
    widget_base_url: str = ""
    # Base URL hosting the SPA (the share-by-link page lives at /c/<key>).
    # Falls back to app_base_url. In a single-origin deploy this equals
    # app_base_url, so leave it blank.
    frontend_base_url: str = ""
    # Filesystem path to the built SPA (frontend/dist). Blank = repo default.
    frontend_dist_dir: str = ""
    # Anonymous abuse guard on public chat: at most N messages per IP+bot within
    # the rolling window. Tenant daily token quota remains the hard backstop.
    public_anon_max_messages: int = 20
    public_anon_window_seconds: int = 600

    # --- Limits / quotas ---
    max_upload_mb: int = 100
    tenant_daily_token_quota: int = 200_000
    tenant_max_documents: int = 200
    retrieval_top_k: int = 5

    # --- Google Calendar OAuth (per-tenant "Connect Google Calendar") ---
    # Blank = the integration is simply unavailable (Settings shows "not
    # configured"); scheduling an interview still works, it just skips the
    # calendar step. See docs/design/ for the Google Cloud Console setup steps.
    google_oauth_client_id: str = ""
    google_oauth_client_secret: str = ""

    # --- Cal.com OAuth ---
    # Cal.com exposes OAuth through its Platform product: you register an OAuth
    # client and are issued endpoints for your own instance, so the URLs are
    # settings rather than constants. Blank client id/secret = the Cal.com card
    # renders as "not configured" and its Connect button stays disabled.
    cal_com_client_id: str = ""
    cal_com_client_secret: str = ""
    cal_com_authorize_url: str = ""
    cal_com_token_url: str = ""

    # --- Resend (candidate interview-invite email) ---
    # Blank = scheduling an interview skips sending email; the admin UI shows a
    # copyable link instead. No hard dependency either way.
    resend_api_key: str = ""
    resend_from_email: str = "interviews@example.com"

    # --- Voice cloning (ElevenLabs) ---
    # Blank = the Clone Voice page still records, stores, and manages samples,
    # but cloning stays in "provider not configured" and no synthesis happens.
    # Same opt-in shape as Google Calendar and Resend.
    elevenlabs_api_key: str = ""
    elevenlabs_model: str = "eleven_multilingual_v2"
    # Guardrails on uploaded samples. The 20s floor is what the UI promises;
    # the ceiling keeps one bad upload from eating the storage bucket.
    voice_sample_min_seconds: int = 20
    voice_sample_max_seconds: int = 300
    voice_sample_max_mb: int = 25

    # --- WhatsApp bridge (personal-account QR linking) ---
    # The Node sidecar that owns the WhatsApp multi-device sockets. Blank token
    # = the feature is off and the Channels page says so; the bridge itself
    # refuses to start without one.
    bridge_token: str = ""
    bridge_base_url: str = "http://127.0.0.1:8081"

    # --- Issue reports ---
    # Where "Report Issue" submissions are emailed. Blank = reports are still
    # persisted and visible in the admin list, they just aren't emailed out.
    support_email: str = ""

    # --- Hiring Agent ---
    # Set HIRING_AGENT_ENABLED=true to mount the /api/v1/hiring/* routes.
    # Off by default so the module is invisible to existing chatbot traffic.
    hiring_agent_enabled: bool = False

    # --- Agent ---
    # Hard ceiling on agent reasoning steps per request (defence against a loop
    # that never converges). Per-request `max_steps` is clamped to this.
    agent_max_steps: int = 6
    # Per-tenant burst guard on the (more expensive) multi-step agent endpoint.
    agent_max_requests: int = 30
    agent_window_seconds: int = 60

    # --- AI observability (all optional; default = no tracing) ---
    # Langfuse: LLM-native traces, generations, and eval scores.
    langfuse_public_key: str = ""
    langfuse_secret_key: str = ""
    langfuse_host: str = ""  # blank = Langfuse Cloud default
    # OpenTelemetry: system-level spans exported by your configured SDK/collector.
    otel_enabled: bool = False
    otel_service_name: str = "rag-platform"

    @property
    def langfuse_enabled(self) -> bool:
        return bool(self.langfuse_public_key and self.langfuse_secret_key)

    @property
    def google_oauth_enabled(self) -> bool:
        return bool(self.google_oauth_client_id and self.google_oauth_client_secret)

    @property
    def google_oauth_redirect_uri(self) -> str:
        return f"{self.app_base_url.rstrip('/')}/api/v1/integrations/google/callback"

    def oauth_redirect_uri(self, provider_id: str) -> str:
        """Where the vendor sends the browser back to. One path per provider, so
        each can be registered separately in the vendor's console.

        Every redirect URI is computed here and nowhere else: they have to match
        what is registered in the vendor console character for character, and a
        second place that builds them is a second place to get them wrong.
        """
        base = self.app_base_url.rstrip("/")
        if provider_id == "google_login":
            # Signing in is not an integration — it stores no tokens and belongs
            # to /auth, so its callback lives there too.
            return f"{base}/api/v1/auth/google/callback"
        return f"{base}/api/v1/integrations/oauth/{provider_id}/callback"

    def oauth_popup_origins(self) -> set[str]:
        """Origins an OAuth popup may hand its result back to.

        This is a security boundary, not a convenience list: the popup posts an
        access token (for sign-in) or a connection result to whichever origin is
        named here, so anything that gets into this set can receive a session.
        Only origins this deployment actually serves are included.

        In development the rule relaxes to any localhost port, because the Vite
        dev server runs on :5173 while the API runs on :8000 and requiring an
        env var to be kept in sync between them is a foot-gun that silently
        breaks the popup handshake.
        """
        origins = {
            base.rstrip("/")
            for base in (self.app_base_url, self.frontend_base_url, self.widget_base_url)
            if base
        }
        return {o for o in origins if o}

    def is_allowed_popup_origin(self, origin: str) -> bool:
        candidate = (origin or "").rstrip("/")
        if not candidate:
            return False
        if candidate in self.oauth_popup_origins():
            return True
        if not self.is_production:
            host = urlsplit(candidate).hostname
            return host in ("localhost", "127.0.0.1", "::1")
        return False

    def oauth_credentials(self, provider_id: str) -> dict[str, str]:
        """Client credentials for one OAuth provider.

        All three Google providers intentionally share one OAuth app — sign-in,
        Calendar and Sheets are the same Google Cloud project differing only in
        the scopes requested, and asking an operator to register a client per
        scope-set would be busywork.
        """
        if provider_id in ("google_login", "google_calendar", "google_sheets"):
            return {
                "client_id": self.google_oauth_client_id,
                "client_secret": self.google_oauth_client_secret,
            }
        if provider_id == "cal_com":
            return {
                "client_id": self.cal_com_client_id,
                "client_secret": self.cal_com_client_secret,
                "authorize_url": self.cal_com_authorize_url,
                "token_url": self.cal_com_token_url,
            }
        return {}

    @property
    def resend_enabled(self) -> bool:
        return bool(self.resend_api_key)

    @property
    def voice_cloning_enabled(self) -> bool:
        return bool(self.elevenlabs_api_key)

    @property
    def whatsapp_bridge_enabled(self) -> bool:
        return bool(self.bridge_token)

    @field_validator("database_url")
    @classmethod
    def _require_async_driver(cls, v: str) -> str:
        # asyncpg is mandatory — the whole stack is async.
        if v.startswith("postgresql://"):
            v = v.replace("postgresql://", "postgresql+asyncpg://", 1)
        return v

    @model_validator(mode="after")
    def _require_strong_secret_in_prod(self) -> Settings:
        # A forgeable JWT secret = full cross-tenant compromise. Fail fast at
        # boot rather than ship a placeholder secret to production.
        if self.app_env == "production" and self.jwt_secret in _INSECURE_JWT_SECRETS:
            raise ValueError(
                "JWT_SECRET must be set to a strong, unique value in production. "
                'Generate one with: python -c "import secrets; '
                'print(secrets.token_urlsafe(48))"'
            )
        return self

    @property
    def use_object_storage(self) -> bool:
        """True when R2 is configured; otherwise we fall back to local disk."""
        return bool(self.r2_endpoint_url and self.r2_access_key_id)

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"

    @property
    def public_widget_base(self) -> str:
        """Origin serving /widget.js and the public API."""
        return (self.widget_base_url or self.app_base_url).rstrip("/")

    @property
    def public_frontend_base(self) -> str:
        """Origin hosting the share-by-link chat page (/c/<key>)."""
        return (self.frontend_base_url or self.app_base_url).rstrip("/")

    @property
    def database_url_async(self) -> str:
        """The DSN with libpq-only query params removed, so it is safe to hand to
        asyncpg. TLS is reapplied separately via `database_connect_args`."""
        parts = urlsplit(self.database_url)
        kept = [
            (k, v)
            for k, v in parse_qsl(parts.query, keep_blank_values=True)
            if k.lower() not in _LIBPQ_ONLY_PARAMS
        ]
        return urlunsplit(parts._replace(query=urlencode(kept)))

    @property
    def database_connect_args(self) -> dict[str, object]:
        """asyncpg connect args. Enables TLS for managed Postgres (anything not
        on a local host, or any DSN that explicitly asked for sslmode/ssl)."""
        parts = urlsplit(self.database_url)
        params = {k.lower(): v.lower() for k, v in parse_qsl(parts.query, keep_blank_values=True)}
        host = (parts.hostname or "").lower()
        wants_ssl = (
            params.get("sslmode") in {"require", "verify-ca", "verify-full", "prefer", "allow"}
            or params.get("ssl") in {"true", "require"}
            or ("sslmode" not in params and host not in _HOSTS_WITHOUT_TLS)
        )
        if not wants_ssl:
            return {}
        if self.database_ssl_verify:
            # asyncpg's `ssl=True` builds a verifying default context.
            return {"ssl": True}
        # Encrypted, but without verifying the chain. Managed providers differ in
        # what they present: Neon serves a publicly trusted certificate, while
        # Supabase's connection pooler is self-signed. Verifying by default makes
        # the app fail to boot at all on the latter — `certificate verify failed:
        # self-signed certificate in certificate chain`, during migrations, so
        # the container exits before serving anything.
        #
        # The traffic is still encrypted; this only skips authenticating the
        # server's identity, matching the sidecar's posture so one DSN works for
        # both. Set DATABASE_SSL_VERIFY=true where the provider's chain is
        # trusted and you want the stronger guarantee.
        context = ssl.create_default_context()
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
        return {"ssl": context}

    # Validate the DSN parses (kept separate so the async prefix is allowed).
    def validate_database_url(self) -> None:
        PostgresDsn(self.database_url_async.replace("+asyncpg", ""))


@lru_cache
def get_settings() -> Settings:
    """Cached settings singleton. Use this everywhere instead of constructing
    `Settings()` directly so config is parsed exactly once per process."""
    return Settings()
