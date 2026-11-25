"""Tests for Prompt 3.2: Light GraphRAG entity extraction and permission-aware 2-hop."""

import uuid

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from api.v1.dependencies import get_embedding_provider
from main import app
from models import (
    Document,
    DocumentChunk,
    DocumentStatus,
    Membership,
    MembershipRole,
    User,
)
from services.graph import GraphService, extract_triples

PASSWORD = "StrongPassw0rd!"


class _ZeroEmbeddings:
    """Zero query embeddings so retrieval must rely on the 2-hop graph path."""

    dimension = 4

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [[0.0, 0.0, 0.0, 0.0] for _ in texts]

    async def embed_query(self, text: str) -> list[float]:
        return [0.0, 0.0, 0.0, 0.0]


def test_extract_triples_from_architecture_sentences() -> None:
    triples = extract_triples("Service A calls Auth API. Auth API uses Redis 7.")
    assert len(triples) == 2
    assert triples[0].source == "Service A"
    assert triples[0].relation == "calls"
    assert triples[0].target == "Auth API"
    assert triples[1].source == "Auth API"
    assert triples[1].relation == "uses"
    assert triples[1].target == "Redis 7"


async def test_two_hop_graph_retrieval_and_rbac_document_grants(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession], monkeypatch
) -> None:
    from core.config import get_settings

    monkeypatch.setattr(get_settings(), "query_cache_enabled", False)
    app.dependency_overrides[get_embedding_provider] = lambda: _ZeroEmbeddings()
    try:
        # Owner + Viewer accounts
        await client.post(
            "/api/v1/auth/register",
            json={"email": "gowner@example.com", "password": PASSWORD},
        )
        owner_token = (
            await client.post(
                "/api/v1/auth/login",
                json={"email": "gowner@example.com", "password": PASSWORD},
            )
        ).json()["access_token"]
        owner_headers = {"Authorization": f"Bearer {owner_token}"}

        await client.post(
            "/api/v1/auth/register",
            json={"email": "gviewer@example.com", "password": PASSWORD},
        )
        viewer_token = (
            await client.post(
                "/api/v1/auth/login",
                json={"email": "gviewer@example.com", "password": PASSWORD},
            )
        ).json()["access_token"]
        viewer_headers = {"Authorization": f"Bearer {viewer_token}"}

        wid = (
            await client.post(
                "/api/v1/workspaces",
                headers=owner_headers,
                json={"name": "Graph WS", "slug": "graph-ws"},
            )
        ).json()["id"]
        ws_uuid = uuid.UUID(wid)

        async with session_factory() as session:
            users = (await session.execute(select(User))).scalars().all()
            owner = next(u for u in users if u.email == "gowner@example.com")
            viewer = next(u for u in users if u.email == "gviewer@example.com")
            session.add(
                Membership(
                    workspace_id=ws_uuid,
                    user_id=viewer.id,
                    role=MembershipRole.MEMBER,
                )
            )

            doc1 = Document(
                workspace_id=ws_uuid,
                uploaded_by=owner.id,
                filename="service-a.md",
                mime_type="text/markdown",
                size=50,
                sha256="1" * 64,
                storage_key=f"{wid}/service-a.md",
                status=DocumentStatus.READY,
                restricted=False,
                embedding_model="test",
                embedding_dim=4,
            )
            doc2 = Document(
                workspace_id=ws_uuid,
                uploaded_by=owner.id,
                filename="auth-api.md",
                mime_type="text/markdown",
                size=50,
                sha256="2" * 64,
                storage_key=f"{wid}/auth-api.md",
                status=DocumentStatus.READY,
                restricted=True,  # Restricted: owner sees it, viewer does NOT!
                embedding_model="test",
                embedding_dim=4,
            )
            session.add_all([doc1, doc2])
            await session.flush()

            c1 = DocumentChunk(
                document_id=doc1.id,
                workspace_id=ws_uuid,
                chunk_index=0,
                content="Service A calls Auth API for session verification.",
                embedding=[0.0, 0.0, 0.0, 0.0],
                search_vector="service a calls auth api",
            )
            c2 = DocumentChunk(
                document_id=doc2.id,
                workspace_id=ws_uuid,
                chunk_index=0,
                content="Auth API uses Redis 7 for distributed token caching.",
                embedding=[0.0, 0.0, 0.0, 0.0],
                search_vector="auth api uses redis 7",
            )
            session.add_all([c1, c2])
            await session.flush()

            graph = GraphService(session)
            await graph.index_document_chunks(ws_uuid, doc1.id, [(c1.id, c1.content)])
            await graph.index_document_chunks(ws_uuid, doc2.id, [(c2.id, c2.content)])
            await session.commit()

        # Owner asks multi-hop question -> 2-hop CTE surfaces BOTH doc1 and doc2
        owner_res = await client.post(
            f"/api/v1/workspaces/{wid}/search",
            headers=owner_headers,
            json={"query": "Does Service A indirectly depend on Redis?"},
        )
        assert owner_res.status_code == 200, owner_res.text
        owner_files = {item["filename"] for item in owner_res.json()["items"]}
        assert "service-a.md" in owner_files
        assert "auth-api.md" in owner_files

        # Viewer asks the same question -> restricted auth-api.md MUST NOT leak!
        viewer_res = await client.post(
            f"/api/v1/workspaces/{wid}/search",
            headers=viewer_headers,
            json={"query": "Does Service A indirectly depend on Redis?"},
        )
        assert viewer_res.status_code == 200, viewer_res.text
        viewer_files = {item["filename"] for item in viewer_res.json()["items"]}
        assert "auth-api.md" not in viewer_files
    finally:
        app.dependency_overrides.pop(get_embedding_provider, None)
