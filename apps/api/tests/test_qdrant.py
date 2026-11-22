"""Tests for the Qdrant mirror: stable ids, filters and PostgreSQL verification."""

import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from core.config import Settings
from core.progress import progress_percent
from models import Document, DocumentChunk, DocumentStatus, QdrantSyncState
from providers.qdrant import collection_name
from repositories import RetrievalRepository
from services.qdrant_index import QdrantIndexService

PROFILE = "ollama-embeddinggemma-768-v1"


class FakeQdrant:
    """Records writes and serves hits without a running Qdrant server."""

    def __init__(self) -> None:
        self.collections: dict[str, dict[str, dict]] = {}
        self.deletes: list[tuple[str, list[dict]]] = []
        self.fail_search = False

    async def ensure_collection(
        self, name: str, dimension: int, distance: str = "Cosine"
    ) -> None:
        self.collections.setdefault(name, {})

    async def get_collection(self, name: str):
        return {"config": {}} if name in self.collections else None

    async def upsert(self, name: str, points, wait: bool = True) -> int:
        for point in points:
            self.collections.setdefault(name, {})[str(point["id"])] = point
        return len(list(points))

    async def delete(
        self, name: str, *, ids=None, must=None, wait: bool = True
    ) -> None:
        self.deletes.append((name, must or []))
        if must:
            conditions = {item["key"]: item["match"]["value"] for item in must}
            for point_id, point in list(self.collections.get(name, {}).items()):
                payload = point["payload"]
                if all(payload.get(key) == value for key, value in conditions.items()):
                    self.collections[name].pop(point_id, None)

    async def search(self, name: str, vector, limit: int, must=None):
        if self.fail_search:
            from providers.qdrant import QdrantUnavailableError

            raise QdrantUnavailableError("down")
        points = list(self.collections.get(name, {}).values())
        return [
            {"id": point["id"], "score": 1.0 - index * 0.1, "payload": point["payload"]}
            for index, point in enumerate(points[:limit])
        ]


@dataclass(frozen=True)
class _Chunk:
    id: uuid.UUID
    document_id: uuid.UUID
    chunk_index: int
    page_number: int | None
    embedding: list[float] | None


def _settings() -> Settings:
    return Settings(qdrant_enabled=True, embedding_profile=PROFILE, embedding_dim=4)


async def _seed(
    factory: async_sessionmaker[AsyncSession],
    workspace_id: uuid.UUID,
    status: DocumentStatus = DocumentStatus.READY,
) -> tuple[uuid.UUID, uuid.UUID]:
    async with factory() as session:
        document = Document(
            workspace_id=workspace_id,
            uploaded_by=uuid.uuid4(),
            filename="doc.txt",
            mime_type="text/plain",
            size=10,
            sha256=uuid.uuid4().hex,
            storage_key=f"{workspace_id}/{uuid.uuid4()}",
            status=status,
            embedding_profile=PROFILE,
            index_version=2,
        )
        session.add(document)
        await session.flush()
        chunk = DocumentChunk(
            document_id=document.id,
            workspace_id=workspace_id,
            chunk_index=0,
            content="alpha beta",
            embedding=[1.0, 0.0, 0.0, 0.0],
            search_vector="alpha beta",
        )
        session.add(chunk)
        await session.commit()
        return document.id, chunk.id


def test_profiles_get_separate_collections() -> None:
    assert collection_name(PROFILE) != collection_name("other-model-768-v1")
    assert collection_name(PROFILE) == collection_name(PROFILE)


async def test_sync_uses_stable_ids_payload_and_checkpoint(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    workspace_id, document_id = uuid.uuid4(), uuid.uuid4()
    chunk_id = uuid.uuid4()
    fake = FakeQdrant()
    indexer = QdrantIndexService(fake, session_factory, _settings())
    chunks = [_Chunk(chunk_id, document_id, 0, 3, [1.0, 0.0, 0.0, 0.0])]

    written = await indexer.sync_chunks(
        workspace_id, document_id, chunks, PROFILE, 2, 4
    )
    assert written == 1
    name = collection_name(PROFILE)
    point = fake.collections[name][str(chunk_id)]
    assert point["payload"]["workspace_id"] == str(workspace_id)
    assert point["payload"]["document_id"] == str(document_id)
    assert point["payload"]["embedding_profile"] == PROFILE
    assert point["payload"]["index_version"] == 2
    assert fake.deletes  # superseded points are removed before the replacement

    # Rerunning is safe: the same ids are overwritten, never duplicated.
    await indexer.sync_chunks(workspace_id, document_id, chunks, PROFILE, 2, 4)
    assert len(fake.collections[name]) == 1
    async with session_factory() as session:
        state = (
            await session.execute(
                select(QdrantSyncState).where(
                    QdrantSyncState.document_id == document_id
                )
            )
        ).scalar_one()
        assert state.status == "completed"
        assert state.chunks_written == 1


async def test_qdrant_hits_are_verified_in_postgres(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    workspace_id, other_workspace = uuid.uuid4(), uuid.uuid4()
    document_id, chunk_id = await _seed(session_factory, workspace_id)
    foreign_document, foreign_chunk = await _seed(session_factory, other_workspace)

    fake = FakeQdrant()
    indexer = QdrantIndexService(fake, session_factory, _settings())
    await indexer.sync_chunks(
        workspace_id,
        document_id,
        [_Chunk(chunk_id, document_id, 0, None, [1.0, 0.0, 0.0, 0.0])],
        PROFILE,
        2,
        4,
    )
    # A stale point from another workspace must never be returned.
    fake.collections[collection_name(PROFILE)][str(foreign_chunk)] = {
        "id": str(foreign_chunk),
        "vector": [1.0, 0.0, 0.0, 0.0],
        "payload": {
            "workspace_id": str(other_workspace),
            "document_id": str(foreign_document),
            "embedding_profile": PROFILE,
            "index_version": 2,
        },
    }
    hits = await fake.search(collection_name(PROFILE), [1.0, 0, 0, 0], 10)
    async with session_factory() as session:
        verified = await RetrievalRepository(session).verify_qdrant_hits(
            workspace_id, hits, None, PROFILE
        )
    assert [item.chunk_id for item in verified] == [chunk_id]
    assert verified[0].content == "alpha beta"


async def test_deleted_document_hit_is_dropped(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    workspace_id = uuid.uuid4()
    document_id, chunk_id = await _seed(session_factory, workspace_id)
    hits = [
        {
            "id": str(chunk_id),
            "score": 0.9,
            "payload": {
                "workspace_id": str(workspace_id),
                "document_id": str(document_id),
                "embedding_profile": PROFILE,
                "index_version": 2,
            },
        },
        {
            "id": str(uuid.uuid4()),
            "score": 0.8,
            "payload": {
                "workspace_id": str(workspace_id),
                "embedding_profile": PROFILE,
                "index_version": 2,
            },
        },
    ]
    async with session_factory() as session:
        # Supersede the index version: the stale point must not be accepted.
        verified = await RetrievalRepository(session).verify_qdrant_hits(
            workspace_id, hits, None, "other-profile"
        )
    assert verified == []


def test_progress_percent_reserves_100_for_ready() -> None:
    @dataclass
    class Doc:
        status: DocumentStatus
        ingestion_stage: str | None
        upload_total: int = 0
        upload_bytes: int = 0
        pages_total: int | None = None
        pages_done: int = 0
        ocr_pages_total: int | None = None
        ocr_pages_done: int = 0
        sections_total: int | None = None
        sections_done: int = 0
        chunks_total: int = 0
        chunks_embedded: int = 0
        chunks_indexed: int = 0

    ready = Doc(DocumentStatus.READY, None, chunks_total=10, chunks_indexed=10)
    assert progress_percent(ready) == 100.0
    reading = Doc(DocumentStatus.PROCESSING, "reading", pages_total=40, pages_done=12)
    assert progress_percent(reading) is not None
    assert 0 < progress_percent(reading) < 100
    unknown = Doc(DocumentStatus.PROCESSING, "reading")
    assert progress_percent(unknown) is None
    failed = Doc(DocumentStatus.FAILED, None)
    assert progress_percent(failed) is None
