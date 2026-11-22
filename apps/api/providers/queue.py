"""Job queue abstraction and ARQ implementation."""

import uuid
from typing import Protocol

from arq import ArqRedis, create_pool
from arq.connections import RedisSettings

from core.config import get_settings

INGEST_JOB = "ingest_document"
PROFILE_SWITCH_JOB = "switch_embedding_profile"
SOURCE_JOB = "ingest_source"

_pool: ArqRedis | None = None


class JobQueue(Protocol):
    async def enqueue_ingest(self, document_id: uuid.UUID) -> str | None:
        """Enqueue document ingestion; returns the ARQ job id, if available."""
        ...

    async def enqueue_profile_switch(
        self, workspace_id: uuid.UUID, profile_name: str
    ) -> str | None:
        """Build a replacement index, then switch the workspace profile."""
        ...

    async def enqueue_source(self, document_id: uuid.UUID) -> str | None:
        """Fetch an external source before the normal ingestion pipeline."""
        ...


async def init_queue_pool() -> ArqRedis:
    """Create the shared ARQ pool (called at app startup)."""
    global _pool
    if _pool is None:
        _pool = await create_pool(RedisSettings.from_dsn(get_settings().redis_url))
    return _pool


def get_arq_pool() -> ArqRedis:
    if _pool is None:
        raise RuntimeError("ARQ pool is not initialized")
    return _pool


async def close_queue_pool() -> None:
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None


class ArqJobQueue:
    def __init__(self, pool: ArqRedis) -> None:
        self._pool = pool

    async def enqueue_ingest(self, document_id: uuid.UUID) -> str | None:
        job = await self._pool.enqueue_job(INGEST_JOB, str(document_id))
        return job.job_id if job is not None else None

    async def enqueue_profile_switch(
        self, workspace_id: uuid.UUID, profile_name: str
    ) -> str | None:
        job = await self._pool.enqueue_job(
            PROFILE_SWITCH_JOB, str(workspace_id), profile_name
        )
        return job.job_id if job is not None else None

    async def enqueue_source(self, document_id: uuid.UUID) -> str | None:
        job = await self._pool.enqueue_job(SOURCE_JOB, str(document_id))
        return job.job_id if job is not None else None
