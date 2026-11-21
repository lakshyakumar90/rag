"""Data access for workspace invitations."""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models import Invitation, InvitationStatus


class InvitationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_token_hash(self, token_hash: str) -> Invitation | None:
        result = await self._session.execute(
            select(Invitation).where(Invitation.token_hash == token_hash)
        )
        return result.scalar_one_or_none()

    async def list_for_workspace(self, workspace_id: uuid.UUID) -> list[Invitation]:
        result = await self._session.execute(
            select(Invitation)
            .where(Invitation.workspace_id == workspace_id)
            .order_by(Invitation.created_at, Invitation.id)
        )
        return list(result.scalars().all())

    async def add(self, invitation: Invitation) -> Invitation:
        self._session.add(invitation)
        await self._session.flush()
        return invitation

    async def revoke_pending(self, workspace_id: uuid.UUID, email: str) -> None:
        """Invalidate older pending invites when re-inviting the same email."""
        result = await self._session.execute(
            select(Invitation).where(
                Invitation.workspace_id == workspace_id,
                Invitation.email == email.strip().lower(),
                Invitation.status == InvitationStatus.PENDING,
            )
        )
        for invitation in result.scalars().all():
            invitation.status = InvitationStatus.REVOKED
