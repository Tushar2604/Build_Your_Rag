"""Request middleware: correlation id binding + request metrics."""

from __future__ import annotations

import time
import uuid

import structlog
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import PlainTextResponse, Response

from src.infrastructure.observability.logging import REQUEST_COUNT, REQUEST_LATENCY

# Public widget endpoints are designed to be called cross-origin from any
# third-party page. The browser-facing CORS layer therefore reflects the request
# Origin (no credentials are ever used on these routes). The actual per-chatbot
# allowlist is enforced inside the route handlers (returning 403) — CORS only
# governs whether the browser will expose that response to the page's JS.
_PUBLIC_PREFIX = "/api/v1/public"
_PUBLIC_CORS_HEADERS = {
    "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type",
    "Access-Control-Max-Age": "600",
}


class PublicCorsMiddleware(BaseHTTPMiddleware):
    """Reflective, credential-free CORS for the public widget API + /widget.js."""

    async def dispatch(self, request: Request, call_next) -> Response:  # type: ignore[no-untyped-def]
        path = request.url.path
        is_public = path.startswith(_PUBLIC_PREFIX) or path == "/widget.js"
        if not is_public:
            return await call_next(request)

        origin = request.headers.get("origin", "*")
        if request.method == "OPTIONS":
            resp: Response = PlainTextResponse("", status_code=204)
        else:
            resp = await call_next(request)

        resp.headers["Access-Control-Allow-Origin"] = origin
        resp.headers["Vary"] = "Origin"
        for key, value in _PUBLIC_CORS_HEADERS.items():
            resp.headers[key] = value
        return resp


class ObservabilityMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:  # type: ignore[no-untyped-def]
        correlation_id = request.headers.get("x-correlation-id", str(uuid.uuid4()))
        structlog.contextvars.bind_contextvars(correlation_id=correlation_id)
        start = time.perf_counter()
        response = await call_next(request)
        elapsed = time.perf_counter() - start

        # Route template is populated during routing (inside call_next). Using it
        # rather than the raw path keeps metric label cardinality bounded.
        route = request.scope.get("route")
        path_label = getattr(route, "path", request.url.path)
        REQUEST_LATENCY.labels(request.method, path_label).observe(elapsed)
        REQUEST_COUNT.labels(request.method, path_label, response.status_code).inc()
        response.headers["x-correlation-id"] = correlation_id
        structlog.contextvars.clear_contextvars()
        return response
