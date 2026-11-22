"""ARQ job: build a replacement embedding index, then switch a workspace."""

import uuid

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from services.embedding_profiles import EmbeddingProfileService
from services.qdrant_index import QdrantIndexService


async def switch_embedding_profile(
    ctx: dict, workspace_id: str, profile_name: str
) -> None:
    factory: async_sessionmaker[AsyncSession] = ctx["session_factory"]
    indexer: QdrantIndexService | None = ctx.get("indexer")
    async with factory() as session:
        service = EmbeddingProfileService(session, None, indexer)
        await service.build_switch(uuid.UUID(workspace_id), profile_name)
