"""ARQ worker configuration (``arq workers.settings.WorkerSettings``)."""

from arq import func
from arq.connections import RedisSettings
from arq.worker import Function

from core.config import get_settings
from core.database import SessionFactory
from providers.minio import MinioStorageClient
from providers.queue import INGEST_JOB
from workers.ingest import ingest_document

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

    functions = [_ingest_function()]
    redis_settings = RedisSettings.from_dsn(settings.redis_url)
    max_jobs = settings.worker_max_jobs
    job_timeout = settings.ingest_job_timeout_seconds + 10
    max_tries = settings.ingest_max_tries
    retry_jobs = True
    # The worker opens its own DB sessions and storage client (no request scope).
    ctx = {"session_factory": SessionFactory, "storage_client": MinioStorageClient()}
