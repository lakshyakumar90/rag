"""Data access for workspace memberships."""

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from models import Membership, MembershipRole, User
from schemas import MemberResponse


class MembershipRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(
        self, user_id: uuid.UUID, workspace_id: uuid.UUID
    ) -> Membership | None:
        result = await self._session.execute(
            select(Membership).where(
                Membership.user_id == user_id,
                Membership.workspace_id == workspace_id,
            )
        )
        return result.scalar_one_or_none()

    async def get_by_email_in_workspace(
        self, email: str, workspace_id: uuid.UUID
    ) -> Membership | None:
        result = await self._session.execute(
            select(Membership)
            .join(User, User.id == Membership.user_id)
            .where(
                User.email == email.strip().lower(),
                Membership.workspace_id == workspace_id,
            )
        )
        return result.scalar_one_or_none()

    async def list_for_user(self, user_id: uuid.UUID) -> list[Membership]:
        result = await self._session.execute(
            select(Membership).where(Membership.user_id == user_id)
        )
        return list(result.scalars().all())

    async def list_for_workspace(self, workspace_id: uuid.UUID) -> list[MemberResponse]:
        result = await self._session.execute(
            select(
                Membership.id,
                Membership.user_id,
                Membership.role,
                Membership.created_at.label("joined_at"),
                User.email,
                User.full_name,
            )
            .join(User, User.id == Membership.user_id)
            .where(Membership.workspace_id == workspace_id)
            .order_by(Membership.created_at, Membership.id)
        )
        return [MemberResponse.model_validate(row) for row in result.all()]

    async def count_owners(self, workspace_id: uuid.UUID) -> int:
        result = await self._session.execute(
            select(func.count())
            .select_from(Membership)
            .where(
                Membership.workspace_id == workspace_id,
                Membership.role == MembershipRole.OWNER,
            )
        )
        return int(result.scalar_one())

    async def add(self, membership: Membership) -> Membership:
        self._session.add(membership)
        await self._session.flush()
        return membership

    async def delete(self, membership: Membership) -> None:
        await self._session.delete(membership)
        await self._session.flush()
