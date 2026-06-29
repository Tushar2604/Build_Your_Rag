"""Object storage adapters.

R2 (S3-compatible) in production; a local-disk fallback for development so the
app runs with zero cloud credentials. The factory picks based on settings.

The local fallback exposes "presigned" URLs that point back at an internal
upload endpoint, so the upload flow is identical in dev and prod.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from src.config import Settings


class R2Storage:
    """Cloudflare R2 via the S3 API (boto3)."""

    def __init__(self, settings: Settings) -> None:
        self._bucket = settings.r2_bucket
        self._settings = settings
        self._client = None

    def _ensure(self):  # type: ignore[no-untyped-def]
        if self._client is None:
            import boto3

            self._client = boto3.client(
                "s3",
                endpoint_url=self._settings.r2_endpoint_url,
                aws_access_key_id=self._settings.r2_access_key_id,
                aws_secret_access_key=self._settings.r2_secret_access_key,
                region_name="auto",
            )
        return self._client

    async def presign_put(self, key: str, content_type: str, max_bytes: int) -> str:
        client = self._ensure()

        def _call() -> str:
            return client.generate_presigned_url(
                "put_object",
                Params={"Bucket": self._bucket, "Key": key, "ContentType": content_type},
                ExpiresIn=900,
            )

        return await asyncio.to_thread(_call)

    async def get_bytes(self, key: str) -> bytes:
        client = self._ensure()

        def _call() -> bytes:
            obj = client.get_object(Bucket=self._bucket, Key=key)
            return obj["Body"].read()

        return await asyncio.to_thread(_call)

    async def put_bytes(self, key: str, data: bytes, content_type: str) -> None:
        client = self._ensure()
        await asyncio.to_thread(
            lambda: client.put_object(
                Bucket=self._bucket, Key=key, Body=data, ContentType=content_type
            )
        )

    async def delete(self, key: str) -> None:
        client = self._ensure()
        await asyncio.to_thread(
            lambda: client.delete_object(Bucket=self._bucket, Key=key)
        )


class LocalDiskStorage:
    """Dev fallback. 'Presigned' PUT points at the app's internal upload route."""

    def __init__(self, settings: Settings) -> None:
        self._root = Path(settings.local_storage_dir)
        self._root.mkdir(parents=True, exist_ok=True)
        self._base_url = settings.app_base_url

    def _path(self, key: str) -> Path:
        path = self._root / key
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    async def presign_put(self, key: str, content_type: str, max_bytes: int) -> str:
        # The client PUTs raw bytes to this internal endpoint (see uploads router).
        return f"{self._base_url}/api/v1/internal/uploads/{key}"

    async def get_bytes(self, key: str) -> bytes:
        return await asyncio.to_thread(self._path(key).read_bytes)

    async def put_bytes(self, key: str, data: bytes, content_type: str) -> None:
        await asyncio.to_thread(self._path(key).write_bytes, data)

    async def delete(self, key: str) -> None:
        path = self._path(key)
        if path.exists():
            await asyncio.to_thread(path.unlink)


def build_storage(settings: Settings):  # type: ignore[no-untyped-def]
    return R2Storage(settings) if settings.use_object_storage else LocalDiskStorage(settings)
