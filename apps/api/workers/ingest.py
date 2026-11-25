"""Background document ingestion task (runs in the ARQ worker container)."""

import asyncio
import contextvars
import logging
import queue
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from arq import Retry
from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from core.config import get_settings
from models import Document, DocumentChunk, DocumentStatus, Workspace
from providers.embeddings import EmbeddingProvider
from providers.storage import StorageClient
from services.qdrant_index import QdrantIndexService
from workers.chunking import chunk_document
from workers.extraction import ExtractionError, extract

logger = logging.getLogger(__name__)

# Poll interval for page-progress events emitted from the extraction thread.
_PROGRESS_POLL_SECONDS = 0.05
# Kept in a context variable so ``_process`` retains its original four-argument
# signature (unit tests monkeypatch it) while still reaching the indexer.
_indexer_var: contextvars.ContextVar["QdrantIndexService | None"] = (
    contextvars.ContextVar("qdrant_indexer", default=None)
)


@dataclass(frozen=True)
class _IndexChunk:
    """Detached chunk values captured before the writing session is closed."""

    id: uuid.UUID
    document_id: uuid.UUID
    chunk_index: int
    page_number: int | None
    embedding: list[float] | None


def _fallback_context_header(
    filename: str,
    heading_path: tuple[str, ...],
    parent_text: str | None,
) -> str:
    """Deterministic structural context header when no LLM is configured."""
    parts = [f"Document: {filename}."]
    if heading_path:
        parts.append(f"Section: {' > '.join(heading_path)}.")
    if parent_text:
        lead = " ".join(parent_text.split()[:24]).strip()
        if lead:
            parts.append(f"Context: {lead}.")
    return " ".join(parts)


async def generate_context_header(
    filename: str,
    heading_path: tuple[str, ...],
    parent_text: str | None,
    child_text: str,
    llm_provider=None,
) -> str:
    """Generate a concise 1-2 sentence contextual retrieval header for a chunk."""
    if llm_provider is not None:
        section_label = " > ".join(heading_path) if heading_path else "General"
        prompt = (
            f"Document: {filename}\nSection: {section_label}\n"
            f"Surrounding section:\n{(parent_text or child_text)[:1500]}\n\n"
            f"Chunk:\n{child_text[:600]}\n\n"
            "Write a concise 1-2 sentence context header naming the document, "
            "section, key entities, and timeframe so this chunk is self-contained "
            "for search. Output only the context sentences."
        )
        try:
            from providers.llm.types import ChatMessage

            resp = await llm_provider.complete(
                [ChatMessage(role="user", content=prompt)],
                max_tokens=96,
                temperature=0.0,
            )
            header = (resp.text or "").strip()
            if header:
                return header[:500]
        except Exception as exc:
            logger.debug("contextual header LLM fallback: %s", exc)
    return _fallback_context_header(filename, heading_path, parent_text)


async def _update_progress(
    factory: async_sessionmaker[AsyncSession], document_id: uuid.UUID, **progress
) -> bool:
    """Commit a progress snapshot. Returns False if the document was cancelled."""
    progress.setdefault("progress_updated_at", datetime.now(UTC))
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


async def _extract_with_progress(
    data: bytes,
    mime_type: str,
    factory: async_sessionmaker[AsyncSession],
    document_id: uuid.UUID,
) -> object:
    """Run extraction off the event loop while streaming reading/OCR progress."""
    events: queue.SimpleQueue[tuple[str, int, int]] = queue.SimpleQueue()

    def emit(phase: str):
        def callback(done: int, total: int) -> None:
            events.put((phase, done, total))

        return callback

    task = asyncio.create_task(
        asyncio.to_thread(extract, data, mime_type, emit("reading"), emit("ocr"))
    )

    async def apply(phase: str, done: int, total: int) -> bool:
        if phase == "ocr":
            snapshot: dict = {
                "ingestion_stage": "ocr",
                "ocr_pages_done": done,
                "ocr_pages_total": total,
            }
        else:
            snapshot = {"ingestion_stage": "reading", "pages_done": done}
            if total > 0:
                snapshot["pages_total"] = total
            else:
                snapshot["sections_done"] = done
        return await _update_progress(factory, document_id, **snapshot)

    while not task.done():
        drained = False
        while True:
            try:
                phase, done, total = events.get_nowait()
            except queue.Empty:
                break
            drained = True
            if not await apply(phase, done, total):
                return await task
        if not drained:
            await asyncio.sleep(_PROGRESS_POLL_SECONDS)
    result = await task
    while True:
        try:
            event = events.get_nowait()
        except queue.Empty:
            break
        await apply(*event)
    return result


async def _process(
    document_id: uuid.UUID,
    factory: async_sessionmaker[AsyncSession],
    storage: StorageClient,
    embeddings: EmbeddingProvider,
) -> None:
    indexer = _indexer_var.get() or QdrantIndexService(None, factory)
    """Download, extract, chunk, embed, index and confirm one document."""
    settings = get_settings()
    profile_name = settings.embedding_profile
    profile_model = settings.ollama_embedding_model
    provider_override = None
    async with factory() as session:
        document = await session.get(Document, document_id)
        if document is None:
            # Deleted while queued: nothing to do.
            return
        workspace = await session.get(Workspace, document.workspace_id)
        profile_name = (
            getattr(workspace, "active_embedding_profile", None) or profile_name
        )
        if profile_name != settings.embedding_profile:
            from types import SimpleNamespace

            from core.crypto import decrypt_secret
            from models import EmbeddingProfile
            from providers.embeddings import get_profile_embedding_provider

            profile = (
                await session.execute(
                    select(EmbeddingProfile).where(
                        EmbeddingProfile.name == profile_name
                    )
                )
            ).scalar_one_or_none()
            if profile is not None:
                config = dict(profile.config_json or {})
                if config.get("encrypted_api_key"):
                    config["api_key"] = decrypt_secret(config["encrypted_api_key"])
                provider_override = get_profile_embedding_provider(
                    SimpleNamespace(
                        provider=profile.provider,
                        model=profile.model,
                        dimension=profile.dimension,
                        config_json=config,
                    )
                )
                profile_model = profile.model
        workspace_id = document.workspace_id
        storage_key = document.storage_key
        mime_type = document.mime_type
        filename = document.filename
        document.status = DocumentStatus.PROCESSING
        document.error = None
        document.ingestion_stage = "reading"
        document.pages_done = 0
        document.ocr_pages_done = 0
        document.sections_done = 0
        document.chunks_embedded = 0
        document.chunks_total = 0
        document.chunks_done = 0
        document.chunks_indexed = 0
        document.unreadable_pages = None
        # A new index version is written only after all previous points have
        # been replaced, so readers never see a half-built index as current.
        document.index_version = (document.index_version or 0) + 1
        document.embedding_profile = profile_name
        document.qdrant_synced_at = None
        index_version = document.index_version
        await session.commit()

    embeddings = provider_override or embeddings
    data = await storage.download(str(workspace_id), storage_key)
    result = await _extract_with_progress(data, mime_type, factory, document_id)
    # The OCR phase is only recorded when there is real OCR work to do;
    # text-only PDFs skip straight from reading to chunking.
    ocr_total = getattr(result, "ocr_pages_total", 0) or 0
    if ocr_total:
        if not await _update_progress(
            factory,
            document_id,
            ingestion_stage="ocr",
            ocr_pages_total=ocr_total,
            ocr_pages_done=ocr_total,
            unreadable_pages=list(getattr(result, "unreadable_pages", []) or [])
            or None,
        ):
            return
    if not await _update_progress(factory, document_id, ingestion_stage="chunking"):
        return

    chunks = await asyncio.to_thread(
        chunk_document,
        result,
        settings.chunking_strategy,
        settings.chunk_target_tokens,
        settings.chunk_overlap_tokens,
        settings.chunk_parent_tokens,
        settings.chunk_child_tokens,
    )
    context_headers: list[str | None] = [None] * len(chunks)
    if settings.contextual_retrieval_enabled and chunks:
        context_headers = [
            await generate_context_header(
                filename,
                chunk.heading_path,
                chunk.parent_text,
                chunk.text,
            )
            for chunk in chunks
        ]
    if not await _update_progress(
        factory,
        document_id,
        ingestion_stage="embedding",
        chunks_total=len(chunks),
        page_count=getattr(result, "page_count", None),
        pages_total=getattr(result, "page_count", None),
        sections_total=len(getattr(result, "sections", [])) or None,
        ocr_pages_total=getattr(result, "ocr_pages_total", None),
        unreadable_pages=list(getattr(result, "unreadable_pages", []) or []) or None,
    ):
        return

    def _contextualized_text(chunk_text: str, header: str | None) -> str:
        return f"{header}\n\n{chunk_text}" if header else chunk_text

    vectors: list[list[float]] = []
    embed_batch_size = max(1, settings.embedding_batch_size)
    for start in range(0, len(chunks), embed_batch_size):
        batch = chunks[start : start + embed_batch_size]
        batch_headers = context_headers[start : start + embed_batch_size]
        vectors.extend(
            await embeddings.embed_documents(
                [
                    _contextualized_text(chunk.text, header)
                    for chunk, header in zip(batch, batch_headers, strict=True)
                ]
            )
        )
        if not await _update_progress(
            factory, document_id, chunks_embedded=len(vectors)
        ):
            return

    if not await _update_progress(factory, document_id, ingestion_stage="indexing"):
        return

    # PostgreSQL first: chunk text, page numbers and headings are the source of
    # truth. The row stays PROCESSING until Qdrant confirms the write, so a
    # partial index is never searchable.
    chunk_rows: list[_IndexChunk] = []
    async with factory() as session:
        document = await session.get(Document, document_id)
        if document is None or document.status != DocumentStatus.PROCESSING:
            return
        await session.execute(
            delete(DocumentChunk).where(DocumentChunk.document_id == document_id)
        )
        batch_size = max(1, settings.chunk_insert_batch_size)
        pairs = list(zip(chunks, vectors, context_headers, strict=True))
        sqlite = session.bind is not None and session.bind.dialect.name == "sqlite"
        for start in range(0, len(pairs), batch_size):
            batch = pairs[start : start + batch_size]
            added = [
                DocumentChunk(
                    document_id=document_id,
                    workspace_id=workspace_id,
                    chunk_index=chunk.index,
                    page_number=chunk.page_number,
                    content=chunk.text,
                    parent_content=chunk.parent_text,
                    context_header=header,
                    char_start=chunk.char_start,
                    char_end=chunk.char_end,
                    heading_path=list(chunk.heading_path) or None,
                    token_count=chunk.token_count,
                    embedding=vector,
                    search_vector=" ".join(
                        _contextualized_text(chunk.text, header).lower().split()
                    )
                    if sqlite
                    else None,
                )
                for chunk, vector, header in batch
            ]
            session.add_all(added)
            await session.flush()
            chunk_rows.extend(
                _IndexChunk(
                    id=row.id,
                    document_id=row.document_id,
                    chunk_index=row.chunk_index,
                    page_number=row.page_number,
                    embedding=list(row.embedding)
                    if row.embedding is not None
                    else None,
                )
                for row in added
            )
            document.chunks_done = len(chunk_rows)
            await session.flush()
        try:
            from services.graph import GraphService

            await GraphService(session).index_document_chunks(
                workspace_id,
                document_id,
                [
                    (row.id, chunk.text)
                    for row, (chunk, _, _) in zip(added, batch, strict=False)
                ],
            )
        except Exception as exc:
            logger.debug("graph extraction skipped: %s", exc)
        await session.commit()

    async def _indexed(written: int) -> None:
        await _update_progress(factory, document_id, chunks_indexed=written)

    if indexer.enabled:
        written = await indexer.sync_chunks(
            workspace_id,
            document_id,
            chunk_rows,
            profile_name,
            index_version,
            embeddings.dimension,
            on_batch=_indexed,
        )
        if written != len(chunk_rows):
            raise RuntimeError(
                f"Qdrant wrote {written} of {len(chunk_rows)} chunks for {document_id}"
            )
    else:
        # Keep the honest count even when the vector store is disabled; the
        # pgvector column in PostgreSQL is the index in that mode.
        for start in range(
            0, len(chunk_rows), max(1, settings.chunk_insert_batch_size)
        ):
            if not await _update_progress(
                factory,
                document_id,
                chunks_indexed=min(
                    len(chunk_rows), start + settings.chunk_insert_batch_size
                ),
            ):
                return

    async with factory() as session:
        document = await session.get(Document, document_id)
        if document is None or document.status != DocumentStatus.PROCESSING:
            return
        document.page_count = getattr(result, "page_count", None)
        document.embedding_model = profile_model
        document.embedding_dim = embeddings.dimension
        document.embedding_profile = profile_name
        document.index_version = index_version
        document.ingestion_stage = None
        document.status = DocumentStatus.READY
        document.qdrant_synced_at = datetime.now(UTC) if indexer.enabled else None
        await session.execute(
            update(Document)
            .where(Document.id == document_id)
            .values(progress_updated_at=func.now())
        )
        await session.commit()
        from services.query_cache import QueryCacheService

        await QueryCacheService(session).invalidate_workspace(workspace_id)

    if provider_override is not None:
        await provider_override.close()


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
            document.progress_updated_at = datetime.now(UTC)
            await session.commit()


async def ingest_document(ctx: dict, document_id: str) -> None:
    """ARQ task: ingest a document, retrying transient failures with backoff."""
    settings = get_settings()
    factory: async_sessionmaker[AsyncSession] = ctx["session_factory"]
    storage: StorageClient = ctx["storage_client"]
    embeddings: EmbeddingProvider = ctx["embedding_provider"]
    indexer: QdrantIndexService | None = ctx.get("indexer")
    if indexer is None and settings.qdrant_enabled:
        from providers.qdrant import shared_qdrant_client

        indexer = QdrantIndexService(await shared_qdrant_client(), factory)
    doc_id = uuid.UUID(document_id)
    attempt = int(ctx.get("job_try", 1))
    logger.info(
        "ingest %s: qdrant_enabled=%s indexer=%s",
        doc_id,
        settings.qdrant_enabled,
        bool(indexer and indexer.enabled),
    )
    token = _indexer_var.set(indexer)

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
        # corrupt file, so fail the row immediately.
        if isinstance(exc, ExtractionError) or attempt >= settings.ingest_max_tries:
            await _record_failure(doc_id, exc, factory)
            raise
        backoff = settings.ingest_retry_backoff_seconds * (2 ** (attempt - 1))
        raise Retry(defer=backoff) from exc
    finally:
        _indexer_var.reset(token)
