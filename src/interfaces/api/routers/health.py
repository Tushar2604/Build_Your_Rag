"""Liveness, readiness, and Prometheus metrics."""

from __future__ import annotations

from fastapi import APIRouter, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from sqlalchemy import text

from src.infrastructure.persistence.database import get_sessionmaker

router = APIRouter(tags=["ops"])


@router.get("/healthz")
async def liveness() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/readyz")
async def readiness() -> Response:
    # Readiness depends on the database being reachable.
    try:
        async with get_sessionmaker()() as session:
            await session.execute(text("SELECT 1"))
        return Response(content='{"status":"ready"}', media_type="application/json")
    except Exception:  # noqa: BLE001
        return Response(
            content='{"status":"not-ready"}',
            media_type="application/json",
            status_code=503,
        )


@router.get("/metrics")
async def metrics() -> Response:
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)
