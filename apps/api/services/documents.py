"""Document upload/listing/deletion business logic."""

import hashlib
import logging
import os
import uuid
from datetime import UTC, datetime
from typing import Protocol

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import get_settings
from core.files import ALLOWED_TYPES, detect_file_type, sanitize_filename
from models import Document, DocumentChunk, DocumentStatus
from providers.minio import StorageError
from providers.queue import JobQueue
from providers.storage import StorageClient
from repositories import DocumentRepository
from schemas import (
    DocumentPage,
    DocumentResponse,
    DownloadUrlResponse,
    SourceCreate,
)
from schemas.document import DocumentSnippetResponse
from services.audit import record as record_audit
from services.document_access import DocumentAccessService
from services.exceptions import (
    DocumentNotFoundError,
    DuplicateDocumentError,
    FileTooLargeError,
    StorageUnavailableError,
    UnsupportedFileTypeError,
)
from services.qdrant_index import QdrantIndexService
from services.query_cache import QueryCacheService
from services.workspaces import WorkspaceContext

_READ_CHUNK = 1024 * 1024
logger = logging.getLogger(__name__)


class DocumentService:
    def __init__(
        self,
        session: AsyncSession,
        storage: StorageClient,
        queue: JobQueue,
        indexer: QdrantIndexService | None = None,
    ) -> None:
        self._session = session
        self._storage = storage
        self._queue = queue
        self._indexer = indexer
        self._documents = DocumentRepository(session)
        self._access = DocumentAccessService(session)

    async def upload(
        self,
        context: WorkspaceContext,
        filename: str,
        data: bytes,
    ) -> DocumentResponse:
        workspace_id = context.workspace.id
        safe_name = sanitize_filename(filename)
        extension = os.path.splitext(safe_name)[1].lower()

        try:
            detected = detect_file_type(data, extension)
        except ValueError as exc:
            raise UnsupportedFileTypeError(str(exc)) from exc

        source_type = "upload"
        source_url: str | None = None
        source_metadata: dict | None = None
        if extension == ".zip":
            from services.sources import notion_zip_to_markdown

            converted = notion_zip_to_markdown(data)
            data = converted.text.encode("utf-8")
            detected = type(detected)(mime_type=converted.mime_type, extension=".md")
            source_type = "notion"
            source_metadata = converted.metadata

        sha256 = hashlib.sha256(data).hexdigest()
        for existing in await self._documents.get_by_sha256(workspace_id, sha256):
            # Failed uploads remain for audit but must not block a retry.
            if existing.status is not DocumentStatus.FAILED:
                raise DuplicateDocumentError(existing.id)

        storage_key = f"{workspace_id}/{uuid.uuid4()}"
        document = Document(
            workspace_id=workspace_id,
            uploaded_by=context.user.id,
            filename=safe_name,
            mime_type=detected.mime_type,
            size=len(data),
            sha256=sha256,
            storage_key=storage_key,
            status=DocumentStatus.PENDING,
            ingestion_stage="queued",
            source_type=source_type,
            source_url=source_url,
            source_metadata=source_metadata,
            upload_bytes=len(data),
            upload_total=len(data),
            embedding_profile=get_settings().embedding_profile,
        )
        await self._documents.add(document, workspace_id)
        try:
            await self._storage.upload(
                str(workspace_id), storage_key, data, detected.mime_type
            )
        except StorageError as exc:
            document.status = DocumentStatus.FAILED
            document.error = str(exc)[:2000]
            await self._session.commit()
            raise StorageUnavailableError() from exc

        # The row stays pending: the ARQ worker moves it through
        # processing/ready (and records failures).
        try:
            await self._session.commit()
        except IntegrityError as exc:
            await self._session.rollback()
            raise DuplicateDocumentError(document.id) from exc

        # Enqueue after commit so the worker never sees a missing row. A queue
        # outage leaves the document pending for a later recovery sweep; it does
        # not undo a successfully stored file.
        try:
            from workers.ocr import is_scanned_pdf

            needs_ocr = is_scanned_pdf(data, detected.mime_type)
            try:
                await self._queue.enqueue_ingest(document.id, needs_ocr=needs_ocr)
            except TypeError:
                await self._queue.enqueue_ingest(document.id)
        except Exception as exc:
            logger.error(
                "could not enqueue ingestion for document %s: %s", document.id, exc
            )

        await record_audit(
            self._session,
            context.user,
            "document.uploaded",
            workspace_id=workspace_id,
            target_type="document",
            target_id=document.id,
        )
        await self._session.commit()
        await QueryCacheService(self._session).invalidate_workspace(workspace_id)
        # updated_at has onupdate=func.now() and is expired by the flush.
        await self._session.refresh(document)
        return DocumentResponse.model_validate(document)

    async def create_source(
        self, context: WorkspaceContext, payload: SourceCreate
    ) -> DocumentResponse:
        """Create a document placeholder for an external source and enqueue it."""
        workspace_id = context.workspace.id
        if payload.type == "url":
            title = (payload.url or "url").rsplit("/", 1)[-1][:200] or "url"
            source_url = payload.url
            metadata: dict = {}
        else:
            title = f"{payload.owner}-{payload.repo}"
            source_url = f"https://github.com/{payload.owner}/{payload.repo}"
            metadata = {
                "owner": payload.owner,
                "repo": payload.repo,
                "ref": payload.ref,
                "path": payload.path,
                "max_depth": payload.max_depth,
            }
        document = Document(
            workspace_id=workspace_id,
            uploaded_by=context.user.id,
            filename=f"{title}.md",
            mime_type="text/markdown",
            size=0,
            sha256=uuid.uuid4().hex,
            storage_key=f"{workspace_id}/source-{uuid.uuid4()}",
            status=DocumentStatus.PENDING,
            ingestion_stage="queued",
            source_type=payload.type,
            source_url=source_url,
            source_metadata=metadata,
            embedding_profile=get_settings().embedding_profile,
        )
        await self._documents.add(document, workspace_id)
        await self._session.commit()
        try:
            await self._queue.enqueue_source(document.id)
        except Exception as exc:
            logger.error("could not enqueue source %s: %s", document.id, exc)
        await self._session.refresh(document)
        return DocumentResponse.model_validate(document)

    async def list_documents(
        self,
        context: WorkspaceContext,
        skip: int = 0,
        limit: int = 50,
        status: DocumentStatus | None = None,
    ) -> DocumentPage:
        workspace_id = context.workspace.id
        role = getattr(context.role, "value", context.role)
        allowed = await self._access.visible_document_ids(
            workspace_id, context.user.id, str(role)
        )
        items = await self._documents.list(workspace_id, skip, limit, status)
        if allowed is not None:
            items = [item for item in items if item.id in set(allowed)]
        total = (
            len(items)
            if allowed is not None
            else await self._documents.count(workspace_id, status)
        )
        return DocumentPage(items=items, total=total, skip=skip, limit=limit)

    async def get(
        self, context: WorkspaceContext, document_id: uuid.UUID
    ) -> DocumentResponse:
        document = await self._documents.get(context.workspace.id, document_id)
        if document is None:
            raise DocumentNotFoundError()
        role = getattr(context.role, "value", context.role)
        if not await self._access.can_access(
            context.workspace.id, context.user.id, str(role), document_id
        ):
            raise DocumentNotFoundError()
        return DocumentResponse.model_validate(document)

    async def snippet(
        self, context: WorkspaceContext, document_id: uuid.UUID, chunk_id: uuid.UUID
    ) -> DocumentSnippetResponse:
        await self.get(context, document_id)
        chunk = await self._session.scalar(
            select(DocumentChunk).where(
                DocumentChunk.id == chunk_id,
                DocumentChunk.document_id == document_id,
                DocumentChunk.workspace_id == context.workspace.id,
            )
        )
        if chunk is None:
            raise DocumentNotFoundError()
        return DocumentSnippetResponse(
            text=chunk.content,
            page_number=chunk.page_number,
            heading_path=chunk.heading_path,
        )

    async def delete(self, context: WorkspaceContext, document_id: uuid.UUID) -> None:
        workspace_id = context.workspace.id
        document = await self._documents.get(workspace_id, document_id)
        if document is None:
            raise DocumentNotFoundError()
        profile = document.embedding_profile

        # Remove the object first: if storage fails, keep the row so it can be
        # retried and is never silently orphaned.
        try:
            await self._storage.delete(str(workspace_id), document.storage_key)
        except StorageError as exc:
            raise StorageUnavailableError() from exc
        await self._documents.delete(document, workspace_id)
        if self._indexer is not None:
            await self._indexer.delete_document(document_id, profile)
        await record_audit(
            self._session,
            context.user,
            "document.deleted",
            workspace_id=workspace_id,
            target_type="document",
            target_id=document_id,
        )
        await self._session.commit()
        await QueryCacheService(self._session).invalidate_workspace(workspace_id)

    async def reindex(
        self, context: WorkspaceContext, document_id: uuid.UUID
    ) -> DocumentResponse:
        """Drop existing chunks and re-run ingestion for a document."""
        workspace_id = context.workspace.id
        document = await self._documents.get(workspace_id, document_id)
        if document is None:
            raise DocumentNotFoundError()
        profile = document.embedding_profile

        # The DB lookup above is workspace-scoped, so this cannot touch another
        # tenant's chunks.
        await self._session.execute(
            delete(DocumentChunk).where(
                DocumentChunk.document_id == document_id,
                DocumentChunk.workspace_id == workspace_id,
            )
        )
        document.status = DocumentStatus.PENDING
        document.error = None
        document.ingestion_stage = "queued"
        document.chunks_embedded = 0
        document.chunks_total = 0
        document.chunks_done = 0
        document.chunks_indexed = 0
        document.pages_done = 0
        document.ocr_pages_done = 0
        document.sections_done = 0
        document.progress_updated_at = datetime.now(UTC)
        await record_audit(
            self._session,
            context.user,
            "document.reindexed",
            workspace_id=workspace_id,
            target_type="document",
            target_id=document_id,
        )
        await self._session.commit()
        await QueryCacheService(self._session).invalidate_workspace(workspace_id)

        if self._indexer is not None:
            await self._indexer.delete_document(document_id, profile)
        try:
            await self._queue.enqueue_ingest(document.id)
        except Exception as exc:
            logger.error(
                "could not enqueue re-index for document %s: %s", document.id, exc
            )
        await self._session.refresh(document)
        return DocumentResponse.model_validate(document)

    async def download_url(
        self, context: WorkspaceContext, document_id: uuid.UUID
    ) -> DownloadUrlResponse:
        workspace_id = context.workspace.id
        document = await self._documents.get(workspace_id, document_id)
        if document is None:
            raise DocumentNotFoundError()
        role = getattr(context.role, "value", context.role)
        if not await self._access.can_access(
            workspace_id, context.user.id, str(role), document_id
        ):
            raise DocumentNotFoundError()
        ttl = get_settings().presigned_url_ttl_seconds
        try:
            url = await self._storage.presigned_url(
                str(workspace_id), document.storage_key, ttl
            )
        except StorageError as exc:
            raise StorageUnavailableError() from exc
        return DownloadUrlResponse(url=url, expires_in=ttl)


class ByteStream(Protocol):
    async def read(self, size: int) -> bytes: ...


async def read_upload(stream: ByteStream, max_bytes: int) -> bytes:
    """Read an upload in bounded chunks, rejecting anything over the limit."""
    chunks: list[bytes] = []
    size = 0
    while True:
        chunk = await stream.read(min(_READ_CHUNK, max_bytes + 1 - size))
        if not chunk:
            break
        chunks.append(chunk)
        size += len(chunk)
        if size > max_bytes:
            raise FileTooLargeError(max_bytes)
    return b"".join(chunks)


def allowed_extensions() -> list[str]:
    return sorted(ALLOWED_TYPES)
