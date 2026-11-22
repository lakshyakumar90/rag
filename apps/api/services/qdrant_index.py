"""Keep the Qdrant vector index consistent with PostgreSQL.

PostgreSQL is the authority for documents, chunks, permissions and text. This
service only mirrors chunk ids and vectors into Qdrant. Every write is
idempotent: a re-index first removes the old points for the same
(document, profile) pair and then upserts stable chunk-id points tagged with an
``index_version``. Retrieval re-checks PostgreSQL before returning any text, so
a stale or partially written point can never expose deleted or unauthorized
content.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Awaitable, Callable, Iterable, Sequence
from datetime import UTC, datetime
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from core.config import Settings, get_settings
from models import Document, QdrantSyncState
from providers.qdrant import (
    QdrantClient,
    collection_name,
    document_filter,
    point_id,
    profile_filter,
)

logger = logging.getLogger(__name__)

ProgressCallback = Callable[[int], Awaitable[None]]


class IndexedChunk(Protocol):
    """The subset of a chunk needed to build a vector point."""

    id: uuid.UUID
    document_id: uuid.UUID
    chunk_index: int
    page_number: int | None
    embedding: list[float] | None


class QdrantIndexService:
    def __init__(
        self,
        client: QdrantClient | None,
        factory: async_sessionmaker[AsyncSession],
        settings: Settings | None = None,
    ) -> None:
        self._client = client
        self._factory = factory
        self._settings = settings or get_settings()

    @property
    def enabled(self) -> bool:
        return self._settings.qdrant_enabled and self._client is not None

    @property
    def client(self) -> QdrantClient | None:
        return self._client

    async def close(self) -> None:
        if self._client is not None:
            await self._client.close()

    @staticmethod
    def payload(
        chunk: IndexedChunk,
        workspace_id: uuid.UUID,
        profile: str,
        index_version: int,
    ) -> dict:
        return {
            "workspace_id": str(workspace_id),
            "document_id": str(chunk.document_id),
            "embedding_profile": profile,
            "index_version": index_version,
            "chunk_index": chunk.chunk_index,
            "page_number": chunk.page_number,
            # Metadata only; text is always read back from PostgreSQL.
        }

    async def prepare(self, profile: str, dimension: int) -> str:
        """Ensure the profile's collection exists and is compatible."""
        assert self._client is not None
        name = collection_name(profile, self._settings.qdrant_collection_prefix)
        await self._client.ensure_collection(name, dimension)
        return name

    async def sync_chunks(
        self,
        workspace_id: uuid.UUID,
        document_id: uuid.UUID,
        chunks: Sequence[IndexedChunk],
        profile: str,
        index_version: int,
        dimension: int,
        on_batch: ProgressCallback | None = None,
    ) -> int:
        """Replace this document's points in Qdrant. Safe to rerun."""
        if not self.enabled:
            return 0
        assert self._client is not None
        name = await self.prepare(profile, dimension)
        # Remove superseded points before writing the replacement. A failure
        # here leaves the previous index intact and the document not ready.
        await self._client.delete(
            name,
            must=[document_filter(document_id), profile_filter(profile)],
            wait=True,
        )
        written = 0
        batch_size = max(1, self._settings.qdrant_batch_size)
        for start in range(0, len(chunks), batch_size):
            batch = chunks[start : start + batch_size]
            points = [
                {
                    "id": point_id(chunk.id),
                    "vector": chunk.embedding,
                    "payload": self.payload(
                        chunk, workspace_id, profile, index_version
                    ),
                }
                for chunk in batch
                if chunk.embedding is not None
            ]
            written += await self._client.upsert(name, points, wait=True)
            if on_batch is not None:
                await on_batch(written)
        await self._checkpoint(
            document_id,
            profile,
            index_version,
            written,
            len(chunks),
            "completed",
        )
        return written

    async def delete_document(
        self, document_id: uuid.UUID, profile: str | None = None
    ) -> None:
        """Remove all points for a document (best effort; PG is authoritative)."""
        if not self.enabled:
            return
        assert self._client is not None
        profiles = [profile] if profile else await self._profiles_for(document_id)
        for item in profiles:
            name = collection_name(item, self._settings.qdrant_collection_prefix)
            try:
                await self._client.delete(
                    name, must=[document_filter(document_id), profile_filter(item)]
                )
            except Exception as exc:  # noqa: BLE001 - cleanup must not delete the PG row
                logger.error(
                    "Qdrant cleanup failed for document %s profile %s: %s",
                    document_id,
                    item,
                    exc,
                )

    async def search(
        self,
        profile: str,
        vector: list[float],
        limit: int,
        workspace_id: uuid.UUID,
        document_ids: Iterable[uuid.UUID] | None = None,
    ) -> list[dict]:
        """Filtered similarity search; returns ids/scores/payload only."""
        assert self._client is not None
        name = collection_name(profile, self._settings.qdrant_collection_prefix)
        must = [profile_filter(profile)]
        # The workspace filter is always applied inside Qdrant, then verified
        # again in PostgreSQL by the retrieval repository.
        from providers.qdrant import workspace_filter

        must.append(workspace_filter(workspace_id))
        if document_ids:
            must.append(
                {"key": "document_id", "match": {"any": [str(d) for d in document_ids]}}
            )
        return await self._client.search(name, vector, limit, must)

    async def _checkpoint(
        self,
        document_id: uuid.UUID,
        profile: str,
        index_version: int,
        written: int,
        total: int,
        status: str,
        error: str | None = None,
    ) -> None:
        async with self._factory() as session:
            existing = (
                await session.execute(
                    select(QdrantSyncState).where(
                        QdrantSyncState.document_id == document_id,
                        QdrantSyncState.embedding_profile == profile,
                    )
                )
            ).scalar_one_or_none()
            now = datetime.now(UTC)
            if existing is None:
                existing = QdrantSyncState(
                    document_id=document_id,
                    embedding_profile=profile,
                    index_version=index_version,
                    chunks_written=written,
                    chunks_total=total,
                    status=status,
                    error=error,
                    completed_at=now if status == "completed" else None,
                )
                session.add(existing)
            else:
                existing.index_version = index_version
                existing.chunks_written = written
                existing.chunks_total = total
                existing.status = status
                existing.error = error
                existing.completed_at = now if status == "completed" else None
            await session.commit()

    async def _profiles_for(self, document_id: uuid.UUID) -> list[str]:
        async with self._factory() as session:
            rows = (
                (
                    await session.execute(
                        select(QdrantSyncState.embedding_profile).where(
                            QdrantSyncState.document_id == document_id
                        )
                    )
                )
                .scalars()
                .all()
            )
            document = await session.get(Document, document_id)
        profiles = list(rows)
        if document is not None and document.embedding_profile:
            profiles.append(document.embedding_profile)
        return list(dict.fromkeys(profiles)) or [self._settings.embedding_profile]
