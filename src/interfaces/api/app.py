"""FastAPI application factory.

Wires middleware, routers, error handlers, and lifespan. On startup it runs the
resume sweep so any document left mid-ingestion by a previous (slept/killed)
process is picked back up.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

import structlog
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from src.application.use_cases.ingest_document import IngestDocument, ResumePendingIngestions
from src.config.container import get_container
from src.config.settings import get_settings
from src.infrastructure.observability.logging import configure_logging
from src.infrastructure.persistence.database import dispose_engine
from src.interfaces.api.errors import register_error_handlers
from src.interfaces.api.middleware import ObservabilityMiddleware, PublicCorsMiddleware
from src.interfaces.api.routers import (
    agent,
    analytics,
    auth,
    broadcasts,
    chat,
    chatbots,
    documents,
    health,
    integrations,
    integrations_catalogue,
    interview_batches,
    interviews,
    oauth,
    post_call,
    public,
    support,
    team,
    uploads,
    voices,
    whatsapp,
    whatsapp_web,
)
from src.hiring_agent.routes import router as hiring_router

_WIDGET_JS = Path(__file__).parent / "static" / "widget.js"
# Built single-page app (admin UI + the public /c/<key> share page). Present in
# production images (the Docker build runs `vite build`); absent in local dev,
# where Vite serves the SPA itself. Override with FRONTEND_DIST_DIR if needed.
_REPO_ROOT = Path(__file__).resolve().parents[3]
_FRONTEND_DIST = Path(
    get_settings().frontend_dist_dir or (_REPO_ROOT / "frontend" / "dist")
)

# Paths owned by the API/ops/widget — never served the SPA fallback.
_NON_SPA_PREFIXES = (
    "api/",
    "healthz",
    "readyz",
    "metrics",
    "widget.js",
    "docs",
    "redoc",
    "openapi.json",
)


def _mount_spa(app: FastAPI) -> None:
    """Serve the built SPA from the API origin so the share page (/c/<key>),
    the admin app, the widget script, and the API all live on ONE domain — which
    is what makes a deployed link work on any visitor's machine. Unknown paths
    fall back to index.html so client-side routing survives a hard refresh."""
    if not _FRONTEND_DIST.is_dir():
        log.info("spa.not_bundled", dist=str(_FRONTEND_DIST))
        return

    assets = _FRONTEND_DIST / "assets"
    if assets.is_dir():
        app.mount("/assets", StaticFiles(directory=assets), name="assets")
    index = _FRONTEND_DIST / "index.html"

    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa(full_path: str) -> FileResponse:
        if full_path.startswith(_NON_SPA_PREFIXES):
            raise HTTPException(status_code=404, detail="Not found")
        candidate = _FRONTEND_DIST / full_path
        if full_path and candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(index)

    log.info("spa.mounted", dist=str(_FRONTEND_DIST))

log = structlog.get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):  # type: ignore[no-untyped-def]
    settings = get_settings()
    configure_logging(settings)
    container = get_container()

    # Resume any ingestion interrupted by a previous process shutdown/sleep.
    try:
        ingest = IngestDocument(
            container.unit_of_work(),
            container.storage,
            container.parser,
            container.chunker,
            container.embedder,
            container.llm,
        )
        resumed = await ResumePendingIngestions(container.unit_of_work(), ingest).execute()
        if resumed:
            log.info("startup.resumed_ingestions", count=resumed)
    except Exception:  # noqa: BLE001 - never block startup on the resume sweep
        log.exception("startup.resume_failed")

    log.info("app.started", env=settings.app_env)
    yield
    # Flush buffered telemetry before the engine/process goes away.
    try:
        await container.tracer.flush()
    except Exception:  # noqa: BLE001 - shutdown best-effort
        log.exception("shutdown.tracer_flush_failed")
    await dispose_engine()
    log.info("app.stopped")


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="RAG Platform",
        version="0.1.0",
        description="Multi-tenant RAG — upload documents, get a working AI chatbot.",
        lifespan=lifespan,
        debug=settings.app_debug,
    )

    # Reflective, credential-free CORS for the public widget API + /widget.js.
    # Added before the authenticated CORS layer so it owns those paths; the
    # standard CORSMiddleware governs the credentialed admin/API surface.
    app.add_middleware(PublicCorsMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_middleware(ObservabilityMiddleware)
    register_error_handlers(app)

    # Ops endpoints at root; everything else under /api/v1.
    app.include_router(health.router)

    @app.get("/widget.js", include_in_schema=False)
    async def widget_js() -> FileResponse:
        """Serve the embeddable widget script. Cached at the edge for an hour;
        the script itself is keyless — it reads its chatbot key from its tag."""
        return FileResponse(
            _WIDGET_JS,
            media_type="application/javascript",
            headers={"Cache-Control": "public, max-age=3600"},
        )

    api_prefix = "/api/v1"
    app.include_router(auth.router, prefix=api_prefix)
    app.include_router(documents.router, prefix=api_prefix)
    app.include_router(chatbots.router, prefix=api_prefix)
    app.include_router(analytics.router, prefix=api_prefix)
    app.include_router(chat.router, prefix=api_prefix)
    app.include_router(agent.router, prefix=api_prefix)
    app.include_router(public.router, prefix=api_prefix)
    app.include_router(uploads.router, prefix=api_prefix)
    app.include_router(interviews.router, prefix=api_prefix)
    app.include_router(interview_batches.router, prefix=api_prefix)
    app.include_router(team.router, prefix=api_prefix)
    app.include_router(integrations.router, prefix=api_prefix)
    app.include_router(whatsapp.router, prefix=api_prefix)
    # Shares the /chatbots prefix with `chatbots` — registered after it so the
    # generic /{chatbot_id} route can't shadow /{chatbot_id}/post-call.
    app.include_router(post_call.router, prefix=api_prefix)
    app.include_router(broadcasts.router, prefix=api_prefix)
    app.include_router(integrations_catalogue.router, prefix=api_prefix)
    app.include_router(oauth.router, prefix=api_prefix)
    app.include_router(support.router, prefix=api_prefix)
    app.include_router(voices.router, prefix=api_prefix)
    app.include_router(whatsapp_web.router, prefix=api_prefix)

    if settings.hiring_agent_enabled:
        app.include_router(hiring_router, prefix=api_prefix)

    # SPA catch-all is mounted LAST so it never shadows the API/ops/widget routes.
    _mount_spa(app)

    return app


app = create_app()
