"""Document upload/listing/deletion business logic."""

import hashlib
import logging
import os
import uuid
from typing import Protocol

from sqlalchemy import delete
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import get_settings
from core.files import ALLOWED_TYPES, detect_file_type, sanitize_filename
from models import Document, DocumentChunk, DocumentStatus
from providers.minio import StorageError
from providers.queue import JobQueue
from providers.storage import StorageClient
from repositories import DocumentRepository
from schemas import DocumentPage, DocumentResponse, DownloadUrlResponse
from services.exceptions import (
    DocumentNotFoundError,
    DuplicateDocumentError,
    FileTooLargeError,
    StorageUnavailableError,
    UnsupportedFileTypeError,
)
from services.workspaces import WorkspaceContext

_READ_CHUNK = 1024 * 1024
logger = logging.getLogger(__name__)


class DocumentService:
    def __init__(
        self,
        session: AsyncSession,
        storage: StorageClient,
        queue: JobQueue,
    ) -> None:
        self._session = session
        self._storage = storage
        self._queue = queue
        self._documents = DocumentRepository(session)

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
            await self._queue.enqueue_ingest(document.id)
        except Exception as exc:
            logger.error(
                "could not enqueue ingestion for document %s: %s", document.id, exc
            )

        # updated_at has onupdate=func.now() and is expired by the flush.
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
        items = await self._documents.list(workspace_id, skip, limit, status)
        total = await self._documents.count(workspace_id, status)
        return DocumentPage(items=items, total=total, skip=skip, limit=limit)

    async def get(
        self, context: WorkspaceContext, document_id: uuid.UUID
    ) -> DocumentResponse:
        document = await self._documents.get(context.workspace.id, document_id)
        if document is None:
            raise DocumentNotFoundError()
        return DocumentResponse.model_validate(document)

    async def delete(self, context: WorkspaceContext, document_id: uuid.UUID) -> None:
        workspace_id = context.workspace.id
        document = await self._documents.get(workspace_id, document_id)
        if document is None:
            raise DocumentNotFoundError()

        # Remove the object first: if storage fails, keep the row so it can be
        # retried and is never silently orphaned.
        try:
            await self._storage.delete(str(workspace_id), document.storage_key)
        except StorageError as exc:
            raise StorageUnavailableError() from exc
        await self._documents.delete(document, workspace_id)
        await self._session.commit()

    async def reindex(
        self, context: WorkspaceContext, document_id: uuid.UUID
    ) -> DocumentResponse:
        """Drop existing chunks and re-run ingestion for a document."""
        workspace_id = context.workspace.id
        document = await self._documents.get(workspace_id, document_id)
        if document is None:
            raise DocumentNotFoundError()

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
        document.chunks_total = 0
        document.chunks_done = 0
        await self._session.commit()

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
