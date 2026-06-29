"""Map domain errors to HTTP responses.

The domain raises framework-agnostic errors; this is the single boundary where
they become HTTP status codes. Registered as exception handlers on the app.
"""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from src.domain.shared.errors import (
    ConflictError,
    DomainError,
    InvalidStateError,
    NotFoundError,
    PermissionDeniedError,
    QuotaExceededError,
    RateLimitedError,
)

_STATUS: dict[type[DomainError], int] = {
    NotFoundError: 404,
    ConflictError: 409,
    PermissionDeniedError: 401,
    QuotaExceededError: 429,
    RateLimitedError: 429,
    InvalidStateError: 422,
}


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(DomainError)
    async def _handle_domain_error(_: Request, exc: DomainError) -> JSONResponse:
        status = next(
            (code for klass, code in _STATUS.items() if isinstance(exc, klass)), 400
        )
        return JSONResponse(
            status_code=status,
            content={"error": exc.__class__.__name__, "detail": str(exc)},
        )
