"""Background document ingestion task (runs in the ARQ worker container)."""

import asyncio
import logging
import uuid

from arq import Retry
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from core.config import get_settings
from models import Document, DocumentStatus

logger = logging.getLogger(__name__)


async def _process(
    document_id: uuid.UUID, factory: async_sessionmaker[AsyncSession]
) -> None:
    """Move a document through ingestion.

    Real chunking/embedding is added in the RAG phase; this step currently
    records the state transitions so the queue/failure machinery is testable.
    """
    async with factory() as session:
        document = await session.get(Document, document_id)
        if document is None:
            # Deleted while queued: nothing to do.
            return
        document.status = DocumentStatus.PROCESSING
        document.error = None
        await session.commit()

    # TODO(5.2): download from storage, extract text, chunk, embed, store.

    async with factory() as session:
        document = await session.get(Document, document_id)
        if document is not None:
            document.status = DocumentStatus.READY
            await session.commit()


async def _record_failure(
    document_id: uuid.UUID, error: Exception, factory: async_sessionmaker[AsyncSession]
) -> None:
    """Persist the terminal failure on the document row."""
    async with factory() as session:
        result = await session.execute(
            select(Document).where(Document.id == document_id)
        )
        document = result.scalar_one_or_none()
        if document is not None:
            document.status = DocumentStatus.FAILED
            document.error = f"{type(error).__name__}: {error}"[:2000]
            await session.commit()


async def ingest_document(ctx: dict, document_id: str) -> None:
    """ARQ task: ingest a document, retrying with backoff before failing."""
    settings = get_settings()
    factory: async_sessionmaker[AsyncSession] = ctx["session_factory"]
    doc_id = uuid.UUID(document_id)
    attempt = int(ctx.get("job_try", 1))

    try:
        # Enforce a timeout inside the task so it is caught by the retry/failure
        # logic (ARQ's own timeout raises CancelledError, which is not an
        # Exception and would bypass this handler).
        await asyncio.wait_for(
            _process(doc_id, factory), timeout=settings.ingest_job_timeout_seconds
        )
    except Exception as exc:
        logger.warning(
            "ingest attempt %d/%d failed for document %s: %s",
            attempt,
            settings.ingest_max_tries,
            doc_id,
            exc,
        )
        if attempt >= settings.ingest_max_tries:
            await _record_failure(doc_id, exc, factory)
            raise
        backoff = settings.ingest_retry_backoff_seconds * (2 ** (attempt - 1))
        raise Retry(defer=backoff) from exc
