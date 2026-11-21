"""MinIO implementation of the storage client.

All calls go through the blocking minio SDK via ``asyncio.to_thread`` so the
async event loop is never blocked by network I/O.
"""

import asyncio
import io
import logging
from datetime import timedelta
from functools import lru_cache

from minio import Minio
from minio.error import S3Error

from core.config import get_settings

logger = logging.getLogger(__name__)


class StorageError(Exception):
    """Object storage is unavailable or rejected an operation."""


@lru_cache(maxsize=1)
def _client() -> Minio:
    settings = get_settings()
    return Minio(
        f"{settings.minio_host}:{settings.minio_port}",
        access_key=settings.minio_root_user,
        secret_key=settings.minio_root_password,
        secure=settings.minio_secure,
    )


class MinioStorageClient:
    def __init__(self, client: Minio | None = None) -> None:
        self._client = client or _client()

    async def _ensure_bucket(self) -> None:
        bucket = get_settings().minio_bucket
        try:
            exists = await asyncio.to_thread(self._client.bucket_exists, bucket)
            if not exists:
                await asyncio.to_thread(self._client.make_bucket, bucket)
        except S3Error as exc:
            raise StorageError(f"cannot access bucket {bucket!r}") from exc
        except Exception as exc:
            raise StorageError("object storage is unavailable") from exc

    @staticmethod
    def _full_key(workspace_id: str, key: str) -> str:
        """Defensively require the key to live under the workspace prefix."""
        if not key.startswith(f"{workspace_id}/"):
            raise StorageError("storage key does not belong to this workspace")
        return key

    async def upload(
        self, workspace_id: str, key: str, data: bytes, content_type: str
    ) -> None:
        full_key = self._full_key(workspace_id, key)
        await self._ensure_bucket()
        try:
            await asyncio.to_thread(
                self._client.put_object,
                get_settings().minio_bucket,
                full_key,
                io.BytesIO(data),
                len(data),
                content_type=content_type,
            )
        except Exception as exc:
            raise StorageError(f"upload failed: {exc}") from exc

    async def download(self, workspace_id: str, key: str) -> bytes:
        full_key = self._full_key(workspace_id, key)
        try:
            response = await asyncio.to_thread(
                self._client.get_object, get_settings().minio_bucket, full_key
            )
            try:
                return response.read()
            finally:
                response.close()
                response.release_conn()
        except Exception as exc:
            raise StorageError(f"download failed: {exc}") from exc

    async def delete(self, workspace_id: str, key: str) -> None:
        full_key = self._full_key(workspace_id, key)
        try:
            await asyncio.to_thread(
                self._client.remove_object, get_settings().minio_bucket, full_key
            )
        except Exception as exc:
            raise StorageError(f"delete failed: {exc}") from exc

    async def presigned_url(
        self, workspace_id: str, key: str, expires_seconds: int
    ) -> str:
        full_key = self._full_key(workspace_id, key)
        try:
            return await asyncio.to_thread(
                self._client.presigned_get_object,
                get_settings().minio_bucket,
                full_key,
                expires=timedelta(seconds=expires_seconds),
            )
        except Exception as exc:
            raise StorageError(f"could not create presigned URL: {exc}") from exc
