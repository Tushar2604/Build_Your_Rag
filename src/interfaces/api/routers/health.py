"""Liveness, readiness, and Prometheus metrics."""

from __future__ import annotations

import os

from fastapi import APIRouter, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from sqlalchemy import text

from src.config.container import get_container
from src.infrastructure.persistence.database import get_sessionmaker

router = APIRouter(tags=["ops"])


@router.get("/healthz")
async def liveness() -> dict[str, str]:
    # The commit is what makes "is my fix actually deployed?" answerable without
    # dashboard access or log archaeology — the question that costs the most
    # time when a deploy silently doesn't land. Render injects RENDER_GIT_COMMIT;
    # elsewhere it is simply absent.
    return {"status": "ok", "commit": os.getenv("RENDER_GIT_COMMIT", "")[:7]}


@router.get("/healthz/bridge")
async def bridge_liveness() -> dict[str, object]:
    """Whether the WhatsApp sidecar is configured and answering.

    Deliberately separate from /healthz: the platform probes that one every few
    seconds, and this makes a network call. Unauthenticated on purpose — it
    reports only two booleans, never the token or the bridge's address, and
    being able to check it without a login is the entire point when pairing is
    failing and nobody can tell whether the sidecar is even alive.
    """
    bridge = get_container().whatsapp_bridge
    if not bridge.enabled:
        return {"configured": False, "reachable": False}
    reachable, error = await bridge.health()
    return {"configured": True, "reachable": reachable, "error": error[:200]}


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
