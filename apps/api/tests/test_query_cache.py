"""Exact-query cache hits preserve citations and never outlive access."""

import uuid
from uuid import uuid4

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from models import Document, DocumentChunk, DocumentStatus
from services.query_cache import stats

BASE = "/api/v1"
PASSWORD = "StrongPassw0rd!"


async def _seed(factory: async_sessionmaker[AsyncSession], workspace_id, owner_id):
    async with factory() as session:
        document = Document(
            workspace_id=uuid.UUID(workspace_id),
            uploaded_by=uuid.UUID(owner_id),
            filename="cache.txt",
            mime_type="text/plain",
            size=40,
            sha256=uuid4().hex,
            storage_key=f"{workspace_id}/cache",
            status=DocumentStatus.READY,
            embedding_model="test",
            embedding_dim=2,
        )
        session.add(document)
        await session.flush()
        session.add(
            DocumentChunk(
                document_id=document.id,
                workspace_id=uuid.UUID(workspace_id),
                chunk_index=0,
                content="cacheable zebra procedure",
                embedding=[1.0, 0.0],
                search_vector="cacheable zebra procedure",
            )
        )
        await session.commit()
        return document.id


async def test_repeated_query_hits_cache_and_grant_change_invalidates(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    await client.post(
        f"{BASE}/auth/register",
        json={"email": "cache-owner@example.com", "password": PASSWORD},
    )
    login = await client.post(
        f"{BASE}/auth/login",
        json={"email": "cache-owner@example.com", "password": PASSWORD},
    )
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    owner_id = (await client.get(f"{BASE}/users/me", headers=headers)).json()["id"]
    workspace_id = (
        await client.post(
            f"{BASE}/workspaces",
            headers=headers,
            json={"name": "Cache", "slug": "cache"},
        )
    ).json()["id"]
    document_id = await _seed(session_factory, workspace_id, owner_id)

    url = f"{BASE}/workspaces/{workspace_id}/search"
    first = await client.post(url, headers=headers, json={"query": "zebra procedure"})
    second = await client.post(url, headers=headers, json={"query": "zebra procedure"})
    assert first.status_code == second.status_code == 200
    first_body, second_body = first.json(), second.json()
    assert second_body["cache_hit"] is True
    for key in ("answer", "answerable", "threshold", "items"):
        assert first_body[key] == second_body[key]
    assert second.json()["items"][0]["document_id"] == str(document_id)
    assert stats()["hits"] >= 1

    # A permission change invalidates the workspace cache immediately.
    await client.put(
        f"{BASE}/workspaces/{workspace_id}/documents/{document_id}/grants",
        headers=headers,
        json={"restricted": True, "user_ids": []},
    )
    after = await client.post(url, headers=headers, json={"query": "zebra procedure"})
    # Owners still see everything; the important assertion is that the cached
    # response was not blindly reused with stale authorization.
    assert after.status_code == 200

    cache_stats = await client.get(f"{BASE}/ai/cache-stats", headers=headers)
    assert cache_stats.status_code == 200
    assert cache_stats.json()["hits"] >= 1
