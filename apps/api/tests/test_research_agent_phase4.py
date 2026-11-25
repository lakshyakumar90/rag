"""Tests for multi-hop decomposition, compare_documents, and GitHub sync."""

import httpx
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from api.v1.dependencies import get_embedding_provider
from main import app
from models import (
    Document,
    DocumentChunk,
    DocumentStatus,
    MembershipRole,
    User,
    Workspace,
)
from services.agent import decompose_query, self_critique_answer
from services.agent_tools import AgentTools
from services.retrieval import RetrievalService
from services.sources import fetch_github_incremental
from services.workspaces import WorkspaceContext


class _SpecEmbeddings:
    dimension = 4

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [await self.embed_query(t) for t in texts]

    async def embed_query(self, text: str) -> list[float]:
        low = text.lower()
        return [
            1.0 if "latency" in low or "ms" in low else 0.1,
            1.0 if "encryption" in low or "security" in low or "aes" in low else 0.1,
            1.0 if "cost" in low or "price" in low else 0.1,
            0.2,
        ]


async def test_decompose_query_and_self_critique() -> None:
    sub_queries = await decompose_query(
        "Compare Spec Alpha and Spec Beta on latency and security encryption"
    )
    assert len(sub_queries) >= 2
    assert any("latency" in q.lower() for q in sub_queries)
    assert any(
        "security" in q.lower() or "encryption" in q.lower() for q in sub_queries
    )

    critique = await self_critique_answer(
        "Compare latency",
        "Spec Alpha has 12ms latency [1]. Spec Beta has 45ms latency [2].",
        "[1] Spec Alpha latency 12ms. [2] Spec Beta latency 45ms.",
    )
    assert "[1]" in critique and "[2]" in critique


async def test_compare_documents_returns_cited_markdown_table(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    app.dependency_overrides[get_embedding_provider] = lambda: _SpecEmbeddings()
    try:
        async with session_factory() as session:
            user = User(email="cmp@example.com", password_hash="hash")
            session.add(user)
            await session.flush()
            ws = Workspace(name="Cmp WS", slug="cmp-ws", created_by=user.id)
            session.add(ws)
            await session.flush()

            doc_a = Document(
                workspace_id=ws.id,
                uploaded_by=user.id,
                filename="spec-alpha.md",
                mime_type="text/markdown",
                size=100,
                sha256="a" * 64,
                storage_key=f"{ws.id}/spec-alpha.md",
                status=DocumentStatus.READY,
                embedding_model="test",
                embedding_dim=4,
            )
            doc_b = Document(
                workspace_id=ws.id,
                uploaded_by=user.id,
                filename="spec-beta.md",
                mime_type="text/markdown",
                size=100,
                sha256="b" * 64,
                storage_key=f"{ws.id}/spec-beta.md",
                status=DocumentStatus.READY,
                embedding_model="test",
                embedding_dim=4,
            )
            session.add_all([doc_a, doc_b])
            await session.flush()
            session.add_all(
                [
                    DocumentChunk(
                        document_id=doc_a.id,
                        workspace_id=ws.id,
                        chunk_index=0,
                        content="Spec Alpha: 12ms p99 latency, AES-256 encryption.",
                        embedding=[1.0, 1.0, 0.1, 0.2],
                        search_vector="spec alpha 12ms p99 latency aes-256 encryption",
                    ),
                    DocumentChunk(
                        document_id=doc_b.id,
                        workspace_id=ws.id,
                        chunk_index=0,
                        content="Spec Beta: 45ms p99 latency, TLS 1.3 security.",
                        embedding=[1.0, 1.0, 0.1, 0.2],
                        search_vector="spec beta 45ms p99 latency tls 1.3 security",
                    ),
                ]
            )
            await session.commit()

            ctx = WorkspaceContext(workspace=ws, user=user, role=MembershipRole.OWNER)
            retrieval = RetrievalService(session, _SpecEmbeddings())
            tools = AgentTools(session, retrieval, ctx)
            result = await tools.compare_documents(
                document_ids=[doc_a.id, doc_b.id],
                criteria=["latency", "security"],
            )
            table = result["markdown_table"]
            assert "| Criterion |" in table
            assert "spec-alpha.md" in table
            assert "spec-beta.md" in table
            assert "[1]" in table
            assert "[2]" in table
            assert len(result["citations"]) >= 2
    finally:
        app.dependency_overrides.pop(get_embedding_provider, None)


async def test_incremental_github_sync_skips_unchanged_files() -> None:
    fetched_urls: list[str] = []

    def _handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        fetched_urls.append(url)
        if "/compare/sha_old...HEAD" in url:
            return httpx.Response(
                200,
                json={
                    "commits": [{"sha": "sha_new_123"}],
                    "files": [
                        {
                            "filename": "docs/architecture.md",
                            "status": "modified",
                            "raw_url": "https://raw.githubusercontent.com/org/repo/sha_new_123/docs/architecture.md",
                        },
                        {
                            "filename": "docs/deprecated.md",
                            "status": "removed",
                        },
                        {
                            "filename": "assets/logo.png",
                            "status": "modified",
                        },
                    ],
                },
            )
        if url.endswith("docs/architecture.md"):
            return httpx.Response(200, text="# Updated Architecture\nNew Redis cache.")
        return httpx.Response(404)

    transport = httpx.MockTransport(_handler)
    async with httpx.AsyncClient(transport=transport) as client:
        sync_res = await fetch_github_incremental(
            "org",
            "repo",
            ref="HEAD",
            last_synced_commit_sha="sha_old",
            http_client=client,
        )

    assert sync_res.head_sha == "sha_new_123"
    assert sync_res.metadata["last_synced_commit_sha"] == "sha_new_123"
    assert sync_res.modified_files == ["docs/architecture.md"]
    assert sync_res.deleted_files == ["docs/deprecated.md"]
    assert "assets/logo.png" in sync_res.skipped_files
    assert "New Redis cache." in sync_res.fetched_contents["docs/architecture.md"]
    # Only the compare endpoint + 1 modified text file were fetched
    assert len(fetched_urls) == 2
