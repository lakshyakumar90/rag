"""Tests for chunk storage, batching, progress and re-indexing."""

import subprocess
import sys
import uuid
from pathlib import Path

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from core.config import get_settings
from core.security import hash_password
from models import Document, DocumentChunk, DocumentStatus, User, Workspace
from workers import ingest

PASSWORD = "StrongPassw0rd!"
API = Path(__file__).resolve().parents[1]


async def _document(factory: async_sessionmaker[AsyncSession], storage, data: bytes):
    async with factory() as session:
        user = User(
            email=f"u-{uuid.uuid4()}@example.com", password_hash=hash_password(PASSWORD)
        )
        session.add(user)
        await session.flush()
        workspace = Workspace(
            name="Acme", slug=f"acme-{uuid.uuid4().hex[:8]}", created_by=user.id
        )
        session.add(workspace)
        await session.flush()
        key = f"{workspace.id}/key"
        document = Document(
            workspace_id=workspace.id,
            uploaded_by=user.id,
            filename="doc.txt",
            mime_type="text/plain",
            size=len(data),
            sha256="a" * 64,
            storage_key=key,
            status=DocumentStatus.PENDING,
        )
        session.add(document)
        await session.commit()
        document_id = document.id
    await storage.upload(str(workspace.id), key, data, "text/plain")
    return document_id


def _ctx(factory, storage, embeddings, job_try: int = 1) -> dict:
    return {
        "job_try": job_try,
        "session_factory": factory,
        "storage_client": storage,
        "embedding_provider": embeddings,
    }


async def _login(client: AsyncClient, email: str) -> dict[str, str]:
    await client.post(
        "/api/v1/auth/register", json={"email": email, "password": PASSWORD}
    )
    response = await client.post(
        "/api/v1/auth/login", json={"email": email, "password": PASSWORD}
    )
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


async def test_batched_inserts_report_progress(
    session_factory: async_sessionmaker[AsyncSession],
    fake_storage,
    fake_embedding_provider,
    monkeypatch,
) -> None:
    monkeypatch.setattr(get_settings(), "chunk_target_tokens", 3)
    monkeypatch.setattr(get_settings(), "chunk_overlap_tokens", 1)
    monkeypatch.setattr(get_settings(), "chunk_insert_batch_size", 2)
    data = b"alpha beta gamma delta epsilon zeta eta theta iota kappa"
    document_id = await _document(session_factory, fake_storage, data)

    await ingest.ingest_document(
        _ctx(session_factory, fake_storage, fake_embedding_provider), str(document_id)
    )

    async with session_factory() as session:
        document = await session.get(Document, document_id)
        assert document is not None
        assert document.status is DocumentStatus.READY
        assert document.chunks_total > 2
        assert document.chunks_done == document.chunks_total
        chunks = (
            (
                await session.execute(
                    select(DocumentChunk).where(
                        DocumentChunk.document_id == document_id
                    )
                )
            )
            .scalars()
            .all()
        )
        assert len(chunks) == document.chunks_total
        assert all(chunk.embedding is not None for chunk in chunks)
        # SQLite stores a text tsvector substitute; PG generates it in the DB.
        assert all(chunk.search_vector for chunk in chunks)


async def test_reindex_resets_chunks_and_enqueues(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    fake_storage,
    fake_embedding_provider,
    fake_job_queue,
) -> None:
    headers = await _login(client, "owner@example.com")
    wid = (
        await client.post(
            "/api/v1/workspaces", headers=headers, json={"name": "Acme", "slug": "acme"}
        )
    ).json()["id"]

    uploaded = await client.post(
        f"/api/v1/workspaces/{wid}/documents",
        headers=headers,
        files={"file": ("doc.txt", b"alpha beta gamma delta epsilon", "text/plain")},
    )
    assert uploaded.status_code == 201
    document_id = uploaded.json()["id"]

    # Simulate the worker having completed the first ingestion.
    await ingest.ingest_document(
        _ctx(session_factory, fake_storage, fake_embedding_provider), document_id
    )
    async with session_factory() as session:
        assert (
            (
                await session.execute(
                    select(DocumentChunk).where(
                        DocumentChunk.document_id == uuid.UUID(document_id)
                    )
                )
            )
            .scalars()
            .all()
        )

    response = await client.post(
        f"/api/v1/workspaces/{wid}/documents/{document_id}/reindex", headers=headers
    )
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "pending"
    assert response.json()["chunks_total"] == 0
    assert response.json()["chunks_done"] == 0
    assert str(uuid.UUID(document_id)) in [str(job) for job in fake_job_queue.jobs]

    async with session_factory() as session:
        remaining = (
            (
                await session.execute(
                    select(DocumentChunk).where(
                        DocumentChunk.document_id == uuid.UUID(document_id)
                    )
                )
            )
            .scalars()
            .all()
        )
        assert remaining == []


async def test_reindex_requires_uploader_role(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    fake_storage,
    fake_embedding_provider,
) -> None:
    owner = await _login(client, "owner@example.com")
    member_headers = await _login(client, "member@example.com")
    wid = (
        await client.post(
            "/api/v1/workspaces", headers=owner, json={"name": "Acme", "slug": "acme"}
        )
    ).json()["id"]
    invite = await client.post(
        f"/api/v1/workspaces/{wid}/invitations",
        headers=owner,
        json={"email": "member@example.com", "role": "member"},
    )
    await client.post(
        "/api/v1/invitations/accept",
        headers=member_headers,
        json={"token": invite.json()["token"]},
    )
    document_id = (
        await client.post(
            f"/api/v1/workspaces/{wid}/documents",
            headers=owner,
            files={"file": ("doc.txt", b"alpha beta gamma delta", "text/plain")},
        )
    ).json()["id"]

    response = await client.post(
        f"/api/v1/workspaces/{wid}/documents/{document_id}/reindex",
        headers=member_headers,
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "INSUFFICIENT_ROLE"


async def test_reindex_cannot_touch_other_workspace(
    client: AsyncClient, fake_storage, fake_job_queue
) -> None:
    a = await _login(client, "owner-a@example.com")
    b = await _login(client, "owner-b@example.com")
    wid_a = (
        await client.post(
            "/api/v1/workspaces", headers=a, json={"name": "A", "slug": "workspace-a"}
        )
    ).json()["id"]
    wid_b = (
        await client.post(
            "/api/v1/workspaces", headers=b, json={"name": "B", "slug": "workspace-b"}
        )
    ).json()["id"]
    doc_b = (
        await client.post(
            f"/api/v1/workspaces/{wid_b}/documents",
            headers=b,
            files={"file": ("doc.txt", b"alpha beta gamma delta", "text/plain")},
        )
    ).json()["id"]

    response = await client.post(
        f"/api/v1/workspaces/{wid_a}/documents/{doc_b}/reindex", headers=a
    )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "DOCUMENT_NOT_FOUND"


def test_migration_sql_contains_vector_and_search_indexes() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head", "--sql"],
        cwd=API,
        capture_output=True,
        text=True,
        check=True,
    )
    sql = result.stdout.lower()
    assert "vector(768)" in sql
    assert "using hnsw" in sql
    assert "vector_cosine_ops" in sql
    assert "using gin" in sql
    assert "to_tsvector" in sql
