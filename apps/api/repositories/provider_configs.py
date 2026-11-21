"""Data access for user-owned provider configs (always filtered by user_id)."""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models import ProviderConfig


class ProviderConfigRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_for_user(self, user_id: uuid.UUID) -> list[ProviderConfig]:
        result = await self._session.execute(
            select(ProviderConfig)
            .where(ProviderConfig.user_id == user_id)
            .order_by(ProviderConfig.created_at, ProviderConfig.id)
        )
        return list(result.scalars().all())

    async def get(
        self, user_id: uuid.UUID, config_id: uuid.UUID
    ) -> ProviderConfig | None:
        result = await self._session.execute(
            select(ProviderConfig).where(
                ProviderConfig.user_id == user_id,
                ProviderConfig.id == config_id,
            )
        )
        return result.scalar_one_or_none()

    async def add(self, config: ProviderConfig) -> ProviderConfig:
        self._session.add(config)
        await self._session.flush()
        return config

    async def delete(self, config: ProviderConfig) -> None:
        await self._session.delete(config)
        await self._session.flush()
