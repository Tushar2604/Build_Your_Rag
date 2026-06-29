"""Internal upload sink for the local-disk storage fallback (dev only).

In production, presigned URLs point directly at Cloudflare R2 and this router is
never hit. In development there is no S3 endpoint, so the "presigned" URL points
here and the raw bytes are written to local disk — keeping the client-side
upload flow identical across environments.
"""

from __future__ import annotations

from fastapi import APIRouter, Request

from src.config.container import get_container

router = APIRouter(prefix="/internal/uploads", tags=["internal"])


@router.put("/{key:path}")
async def put_local_object(key: str, request: Request) -> dict[str, str]:
    container = get_container()
    data = await request.body()
    content_type = request.headers.get("content-type", "application/octet-stream")
    await container.storage.put_bytes(key, data, content_type)
    return {"status": "stored", "key": key}
