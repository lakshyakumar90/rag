"""ARQ worker configurations: fast ingestion (ingest-fast) & OCR (ingest-ocr)."""

from arq import func
from arq.connections import RedisSettings
from arq.worker import Function

from core.config import get_settings
from core.database import SessionFactory
from providers.embeddings import OllamaEmbeddingProvider
from providers.minio import MinioStorageClient
from providers.qdrant import QdrantClient
from providers.queue import (
    EVAL_SUITE_JOB,
    INGEST_FAST_QUEUE,
    INGEST_JOB,
    INGEST_OCR_QUEUE,
    MEMORY_CONSOLIDATE_JOB,
    PROFILE_SWITCH_JOB,
    SOURCE_JOB,
)
from services.qdrant_index import QdrantIndexService
from workers.evals import run_eval_suite
from workers.ingest import ingest_document
from workers.memory import consolidate_turn_memory
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


class _BaseWorkerSettings:
    redis_settings = RedisSettings.from_dsn(settings.redis_url)
    job_timeout = settings.ingest_job_timeout_seconds + 10
    max_tries = settings.ingest_max_tries
    retry_jobs = True
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


class FastWorkerSettings(_BaseWorkerSettings):
    """Handles fast text/MD/DOCX/text-PDF ingestion, profile switches & sources."""

    queue_name = INGEST_FAST_QUEUE
    max_jobs = settings.worker_max_jobs
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
        func(
            run_eval_suite,
            name=EVAL_SUITE_JOB,
            timeout=settings.ingest_job_timeout_seconds + 10,
            max_tries=2,
        ),
        func(
            consolidate_turn_memory,
            name=MEMORY_CONSOLIDATE_JOB,
            timeout=60,
            max_tries=2,
        ),
    ]


class OcrWorkerSettings(_BaseWorkerSettings):
    """Dedicated bounded-concurrency worker for CPU-heavy scanned PDF OCR."""

    queue_name = INGEST_OCR_QUEUE
    max_jobs = settings.worker_ocr_max_jobs
    functions = [_ingest_function()]


# Backwards-compatible alias for `arq workers.settings.WorkerSettings`.
class WorkerSettings(FastWorkerSettings):
    """Default worker settings consuming the ingest-fast queue."""
