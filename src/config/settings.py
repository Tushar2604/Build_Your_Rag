"""Application configuration.

All settings load from environment variables (or a local `.env`). This is the
single source of truth for runtime config — nothing else in the codebase reads
`os.environ` directly. See `.env.example` for documentation of each value.
"""

from __future__ import annotations

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

    # --- Database ---
    database_url: str = "postgresql+asyncpg://rag:rag@localhost:5432/rag"

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

    # --- Resend (candidate interview-invite email) ---
    # Blank = scheduling an interview skips sending email; the admin UI shows a
    # copyable link instead. No hard dependency either way.
    resend_api_key: str = ""
    resend_from_email: str = "interviews@example.com"

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

    @property
    def resend_enabled(self) -> bool:
        return bool(self.resend_api_key)

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
        return {"ssl": True} if wants_ssl else {}

    # Validate the DSN parses (kept separate so the async prefix is allowed).
    def validate_database_url(self) -> None:
        PostgresDsn(self.database_url_async.replace("+asyncpg", ""))


@lru_cache
def get_settings() -> Settings:
    """Cached settings singleton. Use this everywhere instead of constructing
    `Settings()` directly so config is parsed exactly once per process."""
    return Settings()
