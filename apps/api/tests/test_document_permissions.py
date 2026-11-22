"""Per-document grants: revocation removes search, citations and downloads."""

import uuid

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from models import Document, DocumentChunk, DocumentStatus

BASE = "/api/v1"
PASSWORD = "StrongPassw0rd!"


async def _user(client: AsyncClient, email: str) -> dict[str, str]:
    await client.post(
        f"{BASE}/auth/register", json={"email": email, "password": PASSWORD}
    )
    login = await client.post(
        f"{BASE}/auth/login", json={"email": email, "password": PASSWORD}
    )
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


async def _workspace(client: AsyncClient, headers: dict[str, str], slug: str) -> str:
    response = await client.post(
        f"{BASE}/workspaces", headers=headers, json={"name": slug, "slug": slug}
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


async def _seed_document(
    factory: async_sessionmaker[AsyncSession], workspace_id: str, owner_id: str
) -> uuid.UUID:
    async with factory() as session:
        document = Document(
            workspace_id=uuid.UUID(workspace_id),
            uploaded_by=uuid.UUID(owner_id),
            filename="secret.txt",
            mime_type="text/plain",
            size=60,
            sha256=uuid.uuid4().hex,
            storage_key=f"{workspace_id}/secret",
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
                content="confidential alpha procedure",
                embedding=[1.0, 0.0],
                search_vector="confidential alpha procedure",
            )
        )
        await session.commit()
        return document.id


async def test_grants_govern_search_listing_and_downloads(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    owner = await _user(client, "owner-permissions@example.com")
    member = await _user(client, "member-permissions@example.com")
    owner_id = (await client.get(f"{BASE}/users/me", headers=owner)).json()["id"]
    member_id = (await client.get(f"{BASE}/users/me", headers=member)).json()["id"]
    workspace_id = await _workspace(client, owner, "permissions")

    invite = await client.post(
        f"{BASE}/workspaces/{workspace_id}/invitations",
        headers=owner,
        json={"email": "member-permissions@example.com", "role": "member"},
    )
    assert invite.status_code == 201, invite.text
    accepted = await client.post(
        f"{BASE}/invitations/accept",
        headers=member,
        json={"token": invite.json()["token"]},
    )
    assert accepted.status_code == 200, accepted.text

    document_id = await _seed_document(session_factory, workspace_id, owner_id)

    async def search():
        response = await client.post(
            f"{BASE}/workspaces/{workspace_id}/search",
            headers=member,
            json={"query": "confidential alpha"},
        )
        assert response.status_code == 200, response.text
        return response.json()

    # Existing documents inherit the workspace role: visible to members.
    results = (await search())["items"]
    assert len(results) == 1
    chunk_id = results[0]["chunk_id"]
    snippet_url = (
        f"{BASE}/workspaces/{workspace_id}/documents/{document_id}/chunks/{chunk_id}"
    )
    passage = await client.get(snippet_url, headers=member)
    assert passage.status_code == 200, passage.text
    assert passage.json()["text"] == "confidential alpha procedure"
    mismatched = await client.get(
        f"{BASE}/workspaces/{workspace_id}/documents/{document_id}/chunks/{uuid.uuid4()}",
        headers=member,
    )
    assert mismatched.status_code == 404

    restricted = await client.put(
        f"{BASE}/workspaces/{workspace_id}/documents/{document_id}/grants",
        headers=owner,
        json={"restricted": True, "user_ids": []},
    )
    assert restricted.status_code == 200, restricted.text
    assert (await search())["items"] == []
    listed = await client.get(
        f"{BASE}/workspaces/{workspace_id}/documents", headers=member
    )
    assert listed.json()["items"] == []
    download = await client.get(
        f"{BASE}/workspaces/{workspace_id}/documents/{document_id}/url", headers=member
    )
    assert download.status_code == 404
    assert (await client.get(snippet_url, headers=member)).status_code == 404

    granted = await client.put(
        f"{BASE}/workspaces/{workspace_id}/documents/{document_id}/grants",
        headers=owner,
        json={"restricted": True, "user_ids": [member_id]},
    )
    assert granted.status_code == 200, granted.text
    assert granted.json()["user_ids"] == [member_id]
    assert len((await search())["items"]) == 1

    # Revocation takes effect immediately, including cached-style follow-ups.
    await client.put(
        f"{BASE}/workspaces/{workspace_id}/documents/{document_id}/grants",
        headers=owner,
        json={"restricted": True, "user_ids": []},
    )
    assert (await search())["items"] == []
