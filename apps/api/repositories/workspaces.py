"""Data access for workspaces (all reads filtered by workspace_id)."""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models import Membership, Workspace
from repositories.base import ensure_workspace_scope


class WorkspaceRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, workspace_id: uuid.UUID) -> Workspace | None:
        result = await self._session.execute(
            select(Workspace).where(Workspace.id == workspace_id)
        )
        return result.scalar_one_or_none()

    async def get_for_update(self, workspace_id: uuid.UUID) -> Workspace | None:
        """Lock the workspace row to serialize membership/owner changes."""
        result = await self._session.execute(
            select(Workspace).where(Workspace.id == workspace_id).with_for_update()
        )
        return result.scalar_one_or_none()

    async def get_by_slug(
        self, slug: str, *, exclude_workspace_id: uuid.UUID | None = None
    ) -> Workspace | None:
        """Global uniqueness lookup; optionally excludes a workspace being updated."""
        statement = select(Workspace).where(Workspace.slug == slug.strip().lower())
        if exclude_workspace_id is not None:
            statement = statement.where(Workspace.id != exclude_workspace_id)
        result = await self._session.execute(statement)
        return result.scalar_one_or_none()

    async def list_for_user(
        self, user_id: uuid.UUID, *, workspace_id: uuid.UUID | None = None
    ) -> list[Workspace]:
        """List workspaces a user belongs to (optionally narrowed to one)."""
        statement = (
            select(Workspace)
            .join(Membership, Membership.workspace_id == Workspace.id)
            .where(Membership.user_id == user_id)
        )
        if workspace_id is not None:
            statement = statement.where(Workspace.id == workspace_id)
        result = await self._session.execute(
            statement.order_by(Workspace.name, Workspace.id)
        )
        return list(result.scalars().all())

    async def add(self, workspace: Workspace, workspace_id: uuid.UUID) -> Workspace:
        ensure_workspace_scope("Workspace", workspace.id, workspace_id)
        self._session.add(workspace)
        await self._session.flush()
        return workspace

    async def delete(self, workspace: Workspace, workspace_id: uuid.UUID) -> None:
        ensure_workspace_scope("Workspace", workspace.id, workspace_id)
        await self._session.delete(workspace)
        await self._session.flush()
