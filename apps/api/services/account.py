"""Account deletion and workspace data export."""

import logging
import uuid

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from models import (
    Conversation,
    Document,
    Invitation,
    Membership,
    Message,
    ProviderConfig,
    RefreshToken,
    User,
    Workspace,
)
from providers.storage import StorageClient
from services.exceptions import WorkspaceNotFoundError

logger = logging.getLogger(__name__)


class AccountService:
    def __init__(self, session: AsyncSession, storage: StorageClient) -> None:
        self._session = session
        self._storage = storage

    async def delete_account(self, user: User) -> None:
        """Remove the user and everything they own; keep a redacted audit trail."""
        workspace_ids = (
            (
                await self._session.execute(
                    select(Workspace.id).where(Workspace.created_by == user.id)
                )
            )
            .scalars()
            .all()
        )
        document_rows = (
            await self._session.execute(
                select(Document.workspace_id, Document.storage_key).where(
                    (Document.uploaded_by == user.id)
                    | (
                        Document.workspace_id.in_(workspace_ids)
                        if workspace_ids
                        else False
                    )
                )
            )
        ).all()
        for workspace_id, key in document_rows:
            try:
                await self._storage.delete(str(workspace_id), key)
            except Exception as exc:
                logger.warning(
                    "could not remove stored file during account deletion: %s", exc
                )

        for model, column in (
            (Document, Document.workspace_id),
            (Conversation, Conversation.workspace_id),
            (Invitation, Invitation.workspace_id),
            (Membership, Membership.workspace_id),
        ):
            if workspace_ids:
                await self._session.execute(
                    delete(model).where(column.in_(workspace_ids))
                )
        await self._session.execute(
            delete(ProviderConfig).where(ProviderConfig.user_id == user.id)
        )
        await self._session.execute(
            delete(RefreshToken).where(RefreshToken.user_id == user.id)
        )
        if workspace_ids:
            await self._session.execute(
                delete(Workspace).where(Workspace.id.in_(workspace_ids))
            )
        await self._session.delete(user)
        await self._session.commit()

    async def export_workspace(self, workspace_id: uuid.UUID) -> dict:
        """Export metadata for a workspace (file bytes are not included)."""
        workspace = await self._session.get(Workspace, workspace_id)
        if workspace is None:
            raise WorkspaceNotFoundError()
        documents = (
            (
                await self._session.execute(
                    select(Document).where(Document.workspace_id == workspace_id)
                )
            )
            .scalars()
            .all()
        )
        conversations = (
            (
                await self._session.execute(
                    select(Conversation).where(
                        Conversation.workspace_id == workspace_id
                    )
                )
            )
            .scalars()
            .all()
        )
        messages = (
            (
                await self._session.execute(
                    select(Message)
                    .join(Conversation, Conversation.id == Message.conversation_id)
                    .where(Conversation.workspace_id == workspace_id)
                )
            )
            .scalars()
            .all()
        )
        members = (
            (
                await self._session.execute(
                    select(Membership).where(Membership.workspace_id == workspace_id)
                )
            )
            .scalars()
            .all()
        )
        return {
            "workspace": {
                "id": str(workspace.id),
                "name": workspace.name,
                "slug": workspace.slug,
                "created_by": str(workspace.created_by),
            },
            "documents": [
                {
                    "id": str(doc.id),
                    "filename": doc.filename,
                    "mime_type": doc.mime_type,
                    "size": doc.size,
                    "sha256": doc.sha256,
                    "status": doc.status.value,
                    "page_count": doc.page_count,
                    "created_at": doc.created_at.isoformat(),
                }
                for doc in documents
            ],
            "conversations": [
                {
                    "id": str(conversation.id),
                    "title": conversation.title,
                    "user_id": str(conversation.user_id),
                }
                for conversation in conversations
            ],
            "messages": [
                {
                    "id": str(message.id),
                    "conversation_id": str(message.conversation_id),
                    "role": message.role,
                    "content": message.content,
                    "citations": message.citations,
                    "created_at": message.created_at.isoformat(),
                }
                for message in messages
            ],
            "members": [
                {"user_id": str(member.user_id), "role": member.role.value}
                for member in members
            ],
        }
