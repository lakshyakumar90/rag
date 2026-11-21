"""Data access for workspaces."""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models import Membership, Workspace


class WorkspaceRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(self, workspace_id: uuid.UUID) -> Workspace | None:
        return await self._session.get(Workspace, workspace_id)

    async def get_by_id_for_update(self, workspace_id: uuid.UUID) -> Workspace | None:
        """Lock the workspace row to serialize membership/owner changes."""
        result = await self._session.execute(
            select(Workspace).where(Workspace.id == workspace_id).with_for_update()
        )
        return result.scalar_one_or_none()

    async def get_by_slug(self, slug: str) -> Workspace | None:
        result = await self._session.execute(
            select(Workspace).where(Workspace.slug == slug.strip().lower())
        )
        return result.scalar_one_or_none()

    async def list_for_user(self, user_id: uuid.UUID) -> list[Workspace]:
        result = await self._session.execute(
            select(Workspace)
            .join(Membership, Membership.workspace_id == Workspace.id)
            .where(Membership.user_id == user_id)
            .order_by(Workspace.name, Workspace.id)
        )
        return list(result.scalars().all())

    async def add(self, workspace: Workspace) -> Workspace:
        self._session.add(workspace)
        await self._session.flush()
        return workspace

    async def delete(self, workspace: Workspace) -> None:
        await self._session.delete(workspace)
        await self._session.flush()
