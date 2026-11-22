"""ARQ worker configuration (``arq workers.settings.WorkerSettings``)."""

from arq import func
from arq.connections import RedisSettings
from arq.worker import Function

from core.config import get_settings
from core.database import SessionFactory
from providers.embeddings import OllamaEmbeddingProvider
from providers.minio import MinioStorageClient
from providers.qdrant import QdrantClient
from providers.queue import INGEST_JOB, PROFILE_SWITCH_JOB, SOURCE_JOB
from services.qdrant_index import QdrantIndexService
from workers.ingest import ingest_document
from workers.profile_switch import switch_embedding_profile
from workers.source_ingest import ingest_source

settings = get_settings()


def _ingest_function() -> Function:
    return func(
        ingest_document,
        name=INGEST_JOB,
        timeout=settings.ingest_job_timeout_seconds + 10,
        max_tries=settings.ingest_max_tries,
    )


class WorkerSettings:
    """Loaded by the ARQ CLI in the worker container."""

    functions = [
        _ingest_function(),
        func(
            switch_embedding_profile,
            name=PROFILE_SWITCH_JOB,
            timeout=settings.ingest_job_timeout_seconds + 10,
            max_tries=2,
        ),
        func(
            ingest_source,
            name=SOURCE_JOB,
            timeout=settings.ingest_job_timeout_seconds + 10,
            max_tries=settings.ingest_max_tries,
        ),
    ]
    redis_settings = RedisSettings.from_dsn(settings.redis_url)
    max_jobs = settings.worker_max_jobs
    job_timeout = settings.ingest_job_timeout_seconds + 10
    max_tries = settings.ingest_max_tries
    retry_jobs = True
    # The worker opens its own DB sessions, storage and embedding clients.
    _qdrant = QdrantClient() if settings.qdrant_enabled else None
    ctx = {
        "session_factory": SessionFactory,
        "storage_client": MinioStorageClient(),
        "embedding_provider": OllamaEmbeddingProvider(),
        "indexer": QdrantIndexService(_qdrant, SessionFactory),
    }

    @staticmethod
    async def on_shutdown(ctx: dict) -> None:
        indexer: QdrantIndexService | None = ctx.get("indexer")
        if indexer is not None:
            await indexer.close()
