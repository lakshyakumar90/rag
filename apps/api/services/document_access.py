"""Workspace roles plus per-document grants, enforced in one place."""

from __future__ import annotations

import uuid

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from models import Document, DocumentGrant


class DocumentAccessService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def visible_document_ids(
        self,
        workspace_id: uuid.UUID,
        user_id: uuid.UUID,
        role: str,
    ) -> list[uuid.UUID] | None:
        """None means 'every document in the workspace is visible'."""
        if role in ("owner", "admin"):
            return None
        granted = select(DocumentGrant.document_id).where(
            DocumentGrant.workspace_id == workspace_id,
            DocumentGrant.user_id == user_id,
        )
        result = await self._session.execute(
            select(Document.id).where(
                Document.workspace_id == workspace_id,
                or_(Document.restricted.is_(False), Document.id.in_(granted)),
            )
        )
        return list(result.scalars().all())

    async def can_access(
        self,
        workspace_id: uuid.UUID,
        user_id: uuid.UUID,
        role: str,
        document_id: uuid.UUID,
    ) -> bool:
        if role in ("owner", "admin"):
            return True
        document = await self._session.get(Document, document_id)
        if document is None or document.workspace_id != workspace_id:
            return False
        if not document.restricted:
            return True
        grant = (
            await self._session.execute(
                select(DocumentGrant.id).where(
                    DocumentGrant.document_id == document_id,
                    DocumentGrant.workspace_id == workspace_id,
                    DocumentGrant.user_id == user_id,
                )
            )
        ).scalar_one_or_none()
        return grant is not None

    async def set_grants(
        self,
        workspace_id: uuid.UUID,
        document_id: uuid.UUID,
        granted_by: uuid.UUID,
        user_ids: list[uuid.UUID],
        restricted: bool,
    ) -> list[uuid.UUID]:
        """Replace the grant list for a document, idempotently."""
        from sqlalchemy import delete

        document = await self._session.get(Document, document_id)
        if document is None or document.workspace_id != workspace_id:
            return []
        await self._session.execute(
            delete(DocumentGrant).where(
                DocumentGrant.document_id == document_id,
                DocumentGrant.workspace_id == workspace_id,
            )
        )
        document.restricted = restricted
        unique = list(dict.fromkeys(user_ids))
        for target in unique:
            self._session.add(
                DocumentGrant(
                    document_id=document_id,
                    workspace_id=workspace_id,
                    user_id=target,
                    granted_by=granted_by,
                )
            )
        await self._session.commit()
        from services.query_cache import QueryCacheService

        await QueryCacheService(self._session).invalidate_workspace(workspace_id)
        return unique

    async def list_grants(
        self, workspace_id: uuid.UUID, document_id: uuid.UUID
    ) -> list[uuid.UUID]:
        result = await self._session.execute(
            select(DocumentGrant.user_id).where(
                DocumentGrant.document_id == document_id,
                DocumentGrant.workspace_id == workspace_id,
            )
        )
        return list(result.scalars().all())
