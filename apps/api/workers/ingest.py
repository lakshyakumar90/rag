"""Background document ingestion task (runs in the ARQ worker container)."""

import asyncio
import logging
import uuid

from arq import Retry
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from core.config import get_settings
from models import Document, DocumentChunk, DocumentStatus
from providers.embeddings import EmbeddingProvider
from providers.storage import StorageClient
from workers.chunking import chunk_document
from workers.extraction import ExtractionError, extract

logger = logging.getLogger(__name__)


async def _update_progress(
    factory: async_sessionmaker[AsyncSession], document_id: uuid.UUID, **progress
) -> bool:
    async with factory() as session:
        result = await session.execute(
            update(Document)
            .where(
                Document.id == document_id, Document.status == DocumentStatus.PROCESSING
            )
            .values(**progress)
            .returning(Document.id)
        )
        active = result.scalar_one_or_none() is not None
        await session.commit()
        return active


async def _process(
    document_id: uuid.UUID,
    factory: async_sessionmaker[AsyncSession],
    storage: StorageClient,
    embeddings: EmbeddingProvider,
) -> None:
    """Download, extract, chunk, embed and persist one document."""
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
        document.ingestion_stage = "extracting"
        document.chunks_embedded = 0
        document.chunks_total = 0
        document.chunks_done = 0
        await session.commit()

    data = await storage.download(str(workspace_id), storage_key)
    result = await asyncio.to_thread(extract, data, mime_type)
    if not await _update_progress(factory, document_id, ingestion_stage="chunking"):
        return
    settings = get_settings()
    chunks = await asyncio.to_thread(
        chunk_document,
        result,
        settings.chunking_strategy,
        settings.chunk_target_tokens,
        settings.chunk_overlap_tokens,
    )
    if not await _update_progress(
        factory,
        document_id,
        ingestion_stage="embedding",
        chunks_total=len(chunks),
        page_count=result.page_count,
    ):
        return
    vectors: list[list[float]] = []
    embed_batch_size = max(1, settings.embedding_batch_size)
    for start in range(0, len(chunks), embed_batch_size):
        batch = chunks[start : start + embed_batch_size]
        vectors.extend(
            await embeddings.embed_documents([chunk.text for chunk in batch])
        )
        if not await _update_progress(
            factory, document_id, chunks_embedded=len(vectors)
        ):
            return
    if not await _update_progress(factory, document_id, ingestion_stage="indexing"):
        return

    async with factory() as session:
        document = await session.get(Document, document_id)
        if document is None:
            return
        if document.status != DocumentStatus.PROCESSING:
            return
        # Idempotent: reprocessing replaces any previous chunks.
        await session.execute(
            delete(DocumentChunk).where(DocumentChunk.document_id == document_id)
        )
        document.chunks_total = len(chunks)
        document.chunks_done = 0

        # Batch the inserts but keep them in this single transaction: flush
        # advances progress without committing until everything succeeded.
        batch_size = max(1, settings.chunk_insert_batch_size)
        pairs = list(zip(chunks, vectors, strict=True))
        sqlite = session.bind is not None and session.bind.dialect.name == "sqlite"
        for start in range(0, len(pairs), batch_size):
            batch = pairs[start : start + batch_size]
            session.add_all(
                DocumentChunk(
                    document_id=document_id,
                    workspace_id=workspace_id,
                    chunk_index=chunk.index,
                    page_number=chunk.page_number,
                    content=chunk.text,
                    heading_path=list(chunk.heading_path) or None,
                    token_count=chunk.token_count,
                    embedding=vector,
                    # SQLite has no generated tsvector column.
                    search_vector=" ".join(chunk.text.lower().split())
                    if sqlite
                    else None,
                )
                for chunk, vector in batch
            )
            await session.flush()
            document.chunks_done += len(batch)
            await session.flush()

        document.page_count = result.page_count
        document.embedding_model = settings.ollama_embedding_model
        document.embedding_dim = embeddings.dimension
        document.ingestion_stage = None
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
            document.ingestion_stage = None
            document.status = DocumentStatus.FAILED
            document.error = f"{type(error).__name__}: {error}"[:2000]
            await session.commit()


async def ingest_document(ctx: dict, document_id: str) -> None:
    """ARQ task: ingest a document, retrying transient failures with backoff."""
    settings = get_settings()
    factory: async_sessionmaker[AsyncSession] = ctx["session_factory"]
    storage: StorageClient = ctx["storage_client"]
    embeddings: EmbeddingProvider = ctx["embedding_provider"]
    doc_id = uuid.UUID(document_id)
    attempt = int(ctx.get("job_try", 1))

    try:
        # Enforce a timeout inside the task so it is caught by the retry/failure
        # logic (ARQ's own timeout raises CancelledError, which is not an
        # Exception and would bypass this handler).
        await asyncio.wait_for(
            _process(doc_id, factory, storage, embeddings),
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
