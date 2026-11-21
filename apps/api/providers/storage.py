"""Storage abstraction used by the document service."""

from typing import Protocol


class StorageClient(Protocol):
    """Minimal object-storage surface needed for documents.

    Keys are always ``<workspace_id>/<uuid>``; callers never pass a raw key
    that could point into another tenant's prefix.
    """

    async def upload(
        self, workspace_id: str, key: str, data: bytes, content_type: str
    ) -> None: ...

    async def download(self, workspace_id: str, key: str) -> bytes: ...

    async def delete(self, workspace_id: str, key: str) -> None: ...

    async def presigned_url(
        self, workspace_id: str, key: str, expires_seconds: int
    ) -> str: ...
