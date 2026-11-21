"""Data access for documents (all reads filtered by workspace_id)."""

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from models import Document, DocumentStatus
from repositories.base import ensure_workspace_scope
from schemas import DocumentResponse


class DocumentRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(
        self, workspace_id: uuid.UUID, document_id: uuid.UUID
    ) -> Document | None:
        result = await self._session.execute(
            select(Document).where(
                Document.workspace_id == workspace_id,
                Document.id == document_id,
            )
        )
        return result.scalar_one_or_none()

    async def get_by_sha256(
        self, workspace_id: uuid.UUID, sha256: str
    ) -> list[Document]:
        result = await self._session.execute(
            select(Document).where(
                Document.workspace_id == workspace_id,
                Document.sha256 == sha256,
            )
        )
        return list(result.scalars().all())

    async def list(
        self,
        workspace_id: uuid.UUID,
        skip: int,
        limit: int,
        status: DocumentStatus | None,
    ) -> list[DocumentResponse]:
        statement = (
            select(
                Document.id,
                Document.workspace_id,
                Document.uploaded_by,
                Document.filename,
                Document.mime_type,
                Document.size,
                Document.sha256,
                Document.status,
                Document.error,
                Document.page_count,
                Document.chunks_done,
                Document.chunks_total,
                Document.created_at,
                Document.updated_at,
            )
            .where(Document.workspace_id == workspace_id)
            .order_by(Document.created_at.desc(), Document.id.desc())
            .offset(skip)
            .limit(limit)
        )
        if status is not None:
            statement = statement.where(Document.status == status)
        result = await self._session.execute(statement)
        return [DocumentResponse.model_validate(row) for row in result.all()]

    async def count(
        self, workspace_id: uuid.UUID, status: DocumentStatus | None
    ) -> int:
        statement = (
            select(func.count())
            .select_from(Document)
            .where(Document.workspace_id == workspace_id)
        )
        if status is not None:
            statement = statement.where(Document.status == status)
        result = await self._session.execute(statement)
        return int(result.scalar_one())

    async def add(self, document: Document, workspace_id: uuid.UUID) -> Document:
        ensure_workspace_scope("Document", document.workspace_id, workspace_id)
        self._session.add(document)
        await self._session.flush()
        return document

    async def delete(self, document: Document, workspace_id: uuid.UUID) -> None:
        ensure_workspace_scope("Document", document.workspace_id, workspace_id)
        await self._session.delete(document)
        await self._session.flush()
