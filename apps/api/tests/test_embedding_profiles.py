"""BYOK embedding profiles and semantic cache scoping."""

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from core.config import get_settings
from models import Document, DocumentChunk, DocumentStatus, Workspace
from schemas import EmbeddingProfileCreate, SearchResponse
from services.embedding_profiles import EmbeddingProfileService, ProfileInUseError
from services.query_cache import QueryCacheService, stats

PROFILE = "custom-multilingual-v1"


class FakeQueue:
    def __init__(self) -> None:
        self.switches: list[tuple[uuid.UUID, str]] = []

    async def enqueue_profile_switch(self, workspace_id, name):
        self.switches.append((workspace_id, name))
        return "job-1"


class FakeClient:
    def __init__(self) -> None:
        self.points: list[dict] = []

    async def upsert(self, name, points, wait=True):
        self.points.extend(points)
        return len(list(points))


class FakeIndexer:
    enabled = True

    def __init__(self, client):
        self.client = client

    async def prepare(self, name, dimension):
        return name


async def _workspace(factory):
    async with factory() as session:
        workspace = Workspace(
            name="Profiles",
            slug=f"profiles-{uuid.uuid4().hex[:8]}",
            created_by=uuid.uuid4(),
            active_embedding_profile="ollama-embeddinggemma-768-v1",
        )
        session.add(workspace)
        await session.flush()
        document = Document(
            workspace_id=workspace.id,
            uploaded_by=uuid.uuid4(),
            filename="doc.txt",
            mime_type="text/plain",
            size=20,
            sha256=uuid.uuid4().hex,
            storage_key="key",
            status=DocumentStatus.READY,
            embedding_profile="ollama-embeddinggemma-768-v1",
        )
        session.add(document)
        await session.flush()
        session.add(
            DocumentChunk(
                document_id=document.id,
                workspace_id=workspace.id,
                chunk_index=0,
                content="Multilingual profile test content.",
                embedding=[1.0] + [0.0] * 767,
            )
        )
        await session.commit()
        return workspace.id


async def test_profile_lifecycle_and_build_first_switch(
    session_factory: async_sessionmaker[AsyncSession], monkeypatch
) -> None:
    workspace_id = await _workspace(session_factory)

    class FakeProvider:
        dimension = 8

        async def embed_query(self, text):
            return [1.0] + [0.0] * 7

        async def embed_documents(self, texts):
            return [[1.0] + [0.0] * 7 for _ in texts]

        async def close(self):
            return None

    monkeypatch.setattr(
        "services.embedding_profiles.get_profile_embedding_provider",
        lambda profile: FakeProvider(),
    )
    queue = FakeQueue()
    client = FakeClient()
    async with session_factory() as session:
        service = EmbeddingProfileService(session, queue, FakeIndexer(client))
        created = await service.create(
            EmbeddingProfileCreate(
                name=PROFILE,
                provider="ollama",
                model="multilingual-test:latest",
                dimension=8,
                api_key="sk-secret-should-not-leak",
            )
        )
        assert created.enabled is False
        assert created.has_api_key is True
        assert "api_key" not in created.model_dump()

        validated = await service.validate(PROFILE)
        assert validated.ok and validated.dimension == 8

        result = await service.request_switch(workspace_id, PROFILE)
        assert result["profile"] == PROFILE
        assert queue.switches == [(workspace_id, PROFILE)]

        await service.build_switch(workspace_id, PROFILE)
        async with session_factory() as check:
            workspace = await check.get(Workspace, workspace_id)
            assert workspace is not None
            assert workspace.active_embedding_profile == PROFILE
            docs = (await check.execute(select(Document))).scalars().all()
            assert docs[0].embedding_profile == PROFILE
            assert docs[0].index_version == 1
        assert client.points

        with pytest.raises(ProfileInUseError):
            await service.disable(PROFILE)


async def test_semantic_cache_requires_profile_and_threshold(
    session_factory: async_sessionmaker[AsyncSession], monkeypatch
) -> None:
    workspace_id = uuid.uuid4()
    monkeypatch.setattr(get_settings(), "semantic_cache_enabled", True)
    async with session_factory() as session:
        cache = QueryCacheService(session)
        response = SearchResponse(
            answer="alpha", answerable=True, threshold=0.1, items=[]
        )
        await cache.put(
            workspace_id, "exact-key", "auth", response, [1.0, 0.0], PROFILE
        )
        before = stats()["hits"]
        similar = await cache.get(
            workspace_id,
            "different-key",
            "auth",
            None,
            [0.99, 0.01],
            PROFILE,
        )
        assert similar is not None
        assert stats()["hits"] == before + 1
        unrelated = await cache.get(
            workspace_id,
            "another-key",
            "auth",
            None,
            [0.0, 1.0],
            PROFILE,
        )
        assert unrelated is None
        wrong_profile = await cache.get(
            workspace_id,
            "another-key",
            "auth",
            None,
            [0.99, 0.01],
            "other-profile",
        )
        assert wrong_profile is None
