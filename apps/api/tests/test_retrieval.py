"""Tests for hybrid retrieval, RRF fusion, filters, reranking and thresholds."""

import inspect
import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from api.v1.dependencies import get_embedding_provider, get_reranker
from core.config import get_settings
from core.rrf import reciprocal_rank_fusion
from main import app
from models import (
    Document,
    DocumentChunk,
    DocumentStatus,
    User,
)
from providers.rerank import RerankScore
from repositories import RetrievalRepository, ScoredChunk

PASSWORD = "StrongPassw0rd!"
TERMS = ["alpha", "beta", "gamma", "delta"]


@pytest.fixture(autouse=True)
def _keyword_embeddings(client: AsyncClient):
    """Use deterministic one-hot embeddings for every test in this module."""
    # Depends on `client` so this override is applied after the shared fixture.
    app.dependency_overrides[get_embedding_provider] = lambda: KeywordEmbeddings()
    yield
    app.dependency_overrides.pop(get_embedding_provider, None)


class KeywordEmbeddings:
    """One-hot vectors for known terms; unknown terms get a zero vector."""

    dimension = len(TERMS)

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [await self.embed_query(text) for text in texts]

    async def embed_query(self, text: str) -> list[float]:
        vector = [0.0] * self.dimension
        for term in TERMS:
            if term in text.lower():
                vector[TERMS.index(term)] = 1.0
        return vector


class FakeReranker:
    def __init__(self, enabled: bool = True, reverse: bool = True) -> None:
        self.enabled = enabled
        self.reverse = reverse

    async def rerank(self, query: str, texts: list[str]) -> list[RerankScore]:
        order = reversed(range(len(texts))) if self.reverse else range(len(texts))
        return [
            RerankScore(index=i, score=float(i) / max(1, len(texts))) for i in order
        ]


async def _login(client: AsyncClient, email: str) -> dict[str, str]:
    await client.post(
        "/api/v1/auth/register", json={"email": email, "password": PASSWORD}
    )
    response = await client.post(
        "/api/v1/auth/login", json={"email": email, "password": PASSWORD}
    )
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


async def _workspace(client: AsyncClient, headers: dict[str, str], slug: str) -> str:
    response = await client.post(
        "/api/v1/workspaces", headers=headers, json={"name": slug, "slug": slug}
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


async def _seed_document(
    factory: async_sessionmaker[AsyncSession],
    workspace_id: uuid.UUID,
    owner_id: uuid.UUID,
    filename: str,
    text: str,
) -> uuid.UUID:
    async with factory() as session:
        document = Document(
            workspace_id=workspace_id,
            uploaded_by=owner_id,
            filename=filename,
            mime_type="text/plain",
            size=len(text),
            sha256=uuid.uuid4().hex,
            storage_key=f"{workspace_id}/{uuid.uuid4()}",
            status=DocumentStatus.READY,
            embedding_model="test",
            embedding_dim=4,
        )
        session.add(document)
        await session.flush()
        session.add(
            DocumentChunk(
                document_id=document.id,
                workspace_id=workspace_id,
                chunk_index=0,
                content=text,
                embedding=[1.0, 0.0, 0.0, 0.0]
                if "alpha" in text
                else [0.0, 1.0, 0.0, 0.0],
                search_vector=text.lower(),
            )
        )
        await session.commit()
        return document.id


def _chunk(identifier: uuid.UUID, score: float) -> ScoredChunk:
    return ScoredChunk(identifier, identifier, "doc.txt", "text", None, None, score)


def test_rrf_normalizes_and_boosts_overlap() -> None:
    first, second, third = (uuid.uuid4() for _ in range(3))
    fused = reciprocal_rank_fusion(
        [_chunk(first, 0.9), _chunk(second, 0.8)],
        [_chunk(second, 0.7), _chunk(third, 0.6)],
        k=60,
    )
    scores = {item.chunk_id: item.score for item in fused}
    # Both lists rank `second` highly, so its fused score saturates at 1.0.
    assert scores[second] >= scores[first] > scores[third]
    assert scores[first] == pytest.approx(1.0)  # rank 1 in one list
    assert scores[third] == pytest.approx(61 / 62)  # rank 2 in one list
    assert all(0 <= score <= 1 for score in scores.values())


def test_pg_sql_is_workspace_scoped() -> None:
    source = inspect.getsource(RetrievalRepository)
    assert "workspace_id = :workspace_id" in source
    assert "<=> :vector" in source
    assert "ts_rank_cd" in source
    assert "websearch_to_tsquery" in source


async def test_hybrid_search_returns_fused_results(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    headers = await _login(client, "owner@example.com")
    wid = await _workspace(client, headers, "acme")
    async with session_factory() as session:
        user = (await session.execute(select(User))).scalar_one()
        owner_id = user.id
    await _seed_document(
        session_factory, uuid.UUID(wid), owner_id, "a.txt", "alpha beta gamma"
    )

    response = await client.post(
        f"/api/v1/workspaces/{wid}/search", headers=headers, json={"query": "alpha"}
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["answerable"] is True
    assert body["answer"] is None
    assert len(body["items"]) == 1
    assert body["items"][0]["filename"] == "a.txt"
    assert body["items"][0]["score"] > 0


async def test_keyword_only_match_is_found(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    headers = await _login(client, "owner@example.com")
    wid = await _workspace(client, headers, "acme")
    async with session_factory() as session:
        owner_id = (await session.execute(select(User))).scalar_one().id
    # Vector is for "beta", query is "gamma": keyword search must still find it.
    await _seed_document(
        session_factory, uuid.UUID(wid), owner_id, "b.txt", "beta gamma"
    )

    response = await client.post(
        f"/api/v1/workspaces/{wid}/search", headers=headers, json={"query": "gamma"}
    )
    assert response.status_code == 200
    assert len(response.json()["items"]) == 1


async def test_document_filter_and_tenant_isolation(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    a = await _login(client, "a@example.com")
    b = await _login(client, "b@example.com")
    wid_a = await _workspace(client, a, "workspace-a")
    wid_b = await _workspace(client, b, "workspace-b")
    async with session_factory() as session:
        users = (await session.execute(select(User))).scalars().all()
        owner_a = next(user for user in users if user.email == "a@example.com").id
        owner_b = next(user for user in users if user.email == "b@example.com").id

    doc_a = await _seed_document(
        session_factory, uuid.UUID(wid_a), owner_a, "a.txt", "alpha"
    )
    doc_b = await _seed_document(
        session_factory, uuid.UUID(wid_b), owner_b, "b.txt", "alpha"
    )

    filtered = await client.post(
        f"/api/v1/workspaces/{wid_a}/search",
        headers=a,
        json={"query": "alpha", "document_ids": [str(doc_a)]},
    )
    assert filtered.status_code == 200
    assert [item["document_id"] for item in filtered.json()["items"]] == [str(doc_a)]

    # A document id from B is ignored, not leaked.
    foreign = await client.post(
        f"/api/v1/workspaces/{wid_a}/search",
        headers=a,
        json={"query": "alpha", "document_ids": [str(doc_b)]},
    )
    assert foreign.status_code == 200
    assert foreign.json()["items"] == []

    denied = await client.post(
        f"/api/v1/workspaces/{wid_b}/search", headers=a, json={"query": "alpha"}
    )
    assert denied.status_code == 403


async def test_threshold_produces_i_dont_know(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession], monkeypatch
) -> None:
    headers = await _login(client, "owner@example.com")
    wid = await _workspace(client, headers, "acme")
    async with session_factory() as session:
        owner_id = (await session.execute(select(User))).scalar_one().id
    await _seed_document(session_factory, uuid.UUID(wid), owner_id, "a.txt", "alpha")

    # No term matches either index -> empty result -> explicit fallback.
    response = await client.post(
        f"/api/v1/workspaces/{wid}/search", headers=headers, json={"query": "zzzz"}
    )
    assert response.status_code == 200
    assert response.json()["answerable"] is False
    assert response.json()["answer"] == "I don't know"

    # A high threshold rejects even present results.
    monkeypatch.setattr(get_settings(), "retrieval_score_threshold", 2.0)
    strict = await client.post(
        f"/api/v1/workspaces/{wid}/search", headers=headers, json={"query": "alpha"}
    )
    assert strict.json()["answerable"] is False
    assert strict.json()["answer"] == "I don't know"


async def test_reranker_reorders_results(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    headers = await _login(client, "owner@example.com")
    wid = await _workspace(client, headers, "acme")
    async with session_factory() as session:
        owner_id = (await session.execute(select(User))).scalar_one().id
    await _seed_document(session_factory, uuid.UUID(wid), owner_id, "a.txt", "alpha")
    await _seed_document(
        session_factory, uuid.UUID(wid), owner_id, "b.txt", "alpha beta"
    )

    app.dependency_overrides[get_reranker] = lambda: FakeReranker()
    try:
        response = await client.post(
            f"/api/v1/workspaces/{wid}/search", headers=headers, json={"query": "alpha"}
        )
        assert response.status_code == 200
        assert len(response.json()["items"]) == 2
        scores = [item["score"] for item in response.json()["items"]]
        assert scores == sorted(scores, reverse=True)
    finally:
        app.dependency_overrides.pop(get_reranker, None)
