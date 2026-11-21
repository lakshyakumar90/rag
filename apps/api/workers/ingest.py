"""Background document ingestion task (runs in the ARQ worker container)."""

import asyncio
import logging
import uuid

from arq import Retry
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from core.config import get_settings
from models import Document, DocumentChunk, DocumentStatus
from providers.storage import StorageClient
from workers.extraction import ExtractionError, chunk_pages, extract

logger = logging.getLogger(__name__)


async def _process(
    document_id: uuid.UUID,
    factory: async_sessionmaker[AsyncSession],
    storage: StorageClient,
) -> None:
    """Download, extract, clean and chunk one document, then mark it ready."""
    async with factory() as session:
        document = await session.get(Document, document_id)
        if document is None:
            # Deleted while queued: nothing to do.
            return
        workspace_id = document.workspace_id
        storage_key = document.storage_key
        mime_type = document.mime_type
        document.status = DocumentStatus.PROCESSING
        document.error = None
        await session.commit()

    data = await storage.download(str(workspace_id), storage_key)
    result = await asyncio.to_thread(extract, data, mime_type)
    chunks = chunk_pages(result.pages)

    async with factory() as session:
        document = await session.get(Document, document_id)
        if document is None:
            return
        # Idempotent: reprocessing replaces any previous chunks.
        await session.execute(
            delete(DocumentChunk).where(DocumentChunk.document_id == document_id)
        )
        for chunk in chunks:
            session.add(
                DocumentChunk(
                    document_id=document_id,
                    workspace_id=workspace_id,
                    chunk_index=chunk.index,
                    page_number=chunk.page_number,
                    content=chunk.content,
                )
            )
        document.page_count = result.page_count
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
    """ARQ task: ingest a document, retrying transient failures with backoff."""
    settings = get_settings()
    factory: async_sessionmaker[AsyncSession] = ctx["session_factory"]
    storage: StorageClient = ctx["storage_client"]
    doc_id = uuid.UUID(document_id)
    attempt = int(ctx.get("job_try", 1))

    try:
        # Enforce a timeout inside the task so it is caught by the retry/failure
        # logic (ARQ's own timeout raises CancelledError, which is not an
        # Exception and would bypass this handler).
        await asyncio.wait_for(
            _process(doc_id, factory, storage),
            timeout=settings.ingest_job_timeout_seconds,
        )
    except Exception as exc:
        logger.warning(
            "ingest attempt %d/%d failed for document %s: %s",
            attempt,
            settings.ingest_max_tries,
            doc_id,
            exc,
        )
        # Extraction failures are permanent: no amount of retrying fixes a
        # scanned PDF or a corrupt DOCX, so fail the row immediately.
        if isinstance(exc, ExtractionError) or attempt >= settings.ingest_max_tries:
            await _record_failure(doc_id, exc, factory)
            raise
        backoff = settings.ingest_retry_backoff_seconds * (2 ** (attempt - 1))
        raise Retry(defer=backoff) from exc
