"""End-to-end document upload/list/get/delete tests."""

import io
import zipfile
from uuid import uuid4

from httpx import AsyncClient

BASE = "/api/v1"
PASSWORD = "StrongPassw0rd!"
PDF = b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\n%%EOF\n"
TXT = b"Hello, world!\nThis is a document.\n"


def _docx() -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("word/document.xml", "<w:document/>")
        archive.writestr("[Content_Types].xml", "<Types/>")
    return buffer.getvalue()


async def _user(client: AsyncClient, email: str) -> dict[str, str]:
    created = await client.post(
        f"{BASE}/auth/register", json={"email": email, "password": PASSWORD}
    )
    assert created.status_code == 201, created.text
    logged = await client.post(
        f"{BASE}/auth/login", json={"email": email, "password": PASSWORD}
    )
    assert logged.status_code == 200, logged.text
    return {"Authorization": f"Bearer {logged.json()['access_token']}"}


async def _workspace(client: AsyncClient, headers: dict[str, str], slug: str) -> str:
    created = await client.post(
        f"{BASE}/workspaces", headers=headers, json={"name": slug, "slug": slug}
    )
    assert created.status_code == 201, created.text
    return created.json()["id"]


async def _invite_and_accept(
    client: AsyncClient,
    owner: dict[str, str],
    wid: str,
    email: str,
    role: str = "member",
) -> dict[str, str]:
    invite = await client.post(
        f"{BASE}/workspaces/{wid}/invitations",
        headers=owner,
        json={"email": email, "role": role},
    )
    assert invite.status_code == 201, invite.text
    member = await _user(client, email)
    accepted = await client.post(
        f"{BASE}/invitations/accept",
        headers=member,
        json={"token": invite.json()["token"]},
    )
    assert accepted.status_code == 200, accepted.text
    return member


def _upload(
    client: AsyncClient,
    headers: dict[str, str],
    wid: str,
    name: str,
    data: bytes,
    content_type: str = "application/octet-stream",
):
    return client.post(
        f"{BASE}/workspaces/{wid}/documents",
        headers=headers,
        files={"file": (name, data, content_type)},
    )


async def test_upload_list_get_and_delete(client: AsyncClient, fake_storage) -> None:
    owner = await _user(client, "owner@example.com")
    wid = await _workspace(client, owner, "acme")

    response = await _upload(client, owner, wid, "  ../report.pdf ", PDF)
    assert response.status_code == 201, response.text
    doc = response.json()
    assert doc["filename"] == "report.pdf"
    assert doc["mime_type"] == "application/pdf"
    assert doc["size"] == len(PDF)
    assert len(doc["sha256"]) == 64
    assert doc["status"] == "pending"  # the worker will process it
    assert doc["page_count"] is None

    # Stored under workspace_id/uuid, never under the client-supplied name.
    key = next(iter(fake_storage.objects))[1]
    assert key.startswith(f"{wid}/")
    assert "/" not in key[len(wid) + 1 :]
    assert fake_storage.objects[(wid, key)] == PDF

    listed = await client.get(f"{BASE}/workspaces/{wid}/documents", headers=owner)
    assert listed.status_code == 200
    assert listed.json()["total"] == 1
    assert [item["id"] for item in listed.json()["items"]] == [doc["id"]]

    fetched = await client.get(
        f"{BASE}/workspaces/{wid}/documents/{doc['id']}", headers=owner
    )
    assert fetched.status_code == 200
    assert fetched.json()["filename"] == "report.pdf"

    url = await client.get(
        f"{BASE}/workspaces/{wid}/documents/{doc['id']}/url", headers=owner
    )
    assert url.status_code == 200
    assert url.json()["expires_in"] > 0
    assert wid in url.json()["url"]

    deleted = await client.delete(
        f"{BASE}/workspaces/{wid}/documents/{doc['id']}", headers=owner
    )
    assert deleted.status_code == 204
    assert fake_storage.objects == {}
    assert (
        await client.get(f"{BASE}/workspaces/{wid}/documents", headers=owner)
    ).json()["total"] == 0


async def test_pagination_and_status_filter(client: AsyncClient) -> None:
    owner = await _user(client, "owner@example.com")
    wid = await _workspace(client, owner, "acme")
    for index in range(3):
        response = await _upload(
            client, owner, wid, f"note-{index}.txt", f"note {index}".encode()
        )
        assert response.status_code == 201, response.text

    page = await client.get(
        f"{BASE}/workspaces/{wid}/documents",
        headers=owner,
        params={"skip": 1, "limit": 1},
    )
    assert page.status_code == 200
    body = page.json()
    assert body["total"] == 3 and body["skip"] == 1 and body["limit"] == 1
    assert len(body["items"]) == 1

    filtered = await client.get(
        f"{BASE}/workspaces/{wid}/documents",
        headers=owner,
        params={"status": "pending"},
    )
    assert filtered.json()["total"] == 3
    none = await client.get(
        f"{BASE}/workspaces/{wid}/documents",
        headers=owner,
        params={"status": "failed"},
    )
    assert none.json()["total"] == 0


async def test_oversize_file_rejected(client: AsyncClient, monkeypatch) -> None:
    from core.config import get_settings

    monkeypatch.setattr(get_settings(), "max_upload_size_bytes", 10)
    owner = await _user(client, "owner@example.com")
    wid = await _workspace(client, owner, "acme")
    response = await _upload(client, owner, wid, "big.txt", b"x" * 11)
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "FILE_TOO_LARGE"
    assert response.json()["error"]["details"]["max_size_bytes"] == 10


async def test_wrong_types_rejected(client: AsyncClient) -> None:
    owner = await _user(client, "owner@example.com")
    wid = await _workspace(client, owner, "acme")

    # Disallowed extension.
    response = await _upload(client, owner, wid, "evil.exe", b"MZ\x90")
    assert response.status_code == 415
    assert response.json()["error"]["code"] == "UNSUPPORTED_FILE_TYPE"

    # Allowed extension, wrong magic bytes.
    response = await _upload(client, owner, wid, "fake.pdf", b"not a pdf")
    assert response.status_code == 415
    assert "not a PDF" in response.json()["error"]["message"]

    # ZIP that is not a DOCX.
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("other.txt", "hello")
    response = await _upload(client, owner, wid, "fake.docx", buffer.getvalue())
    assert response.status_code == 415
    assert "word/document.xml" in response.json()["error"]["message"]

    # No documents were stored for any rejection.
    assert (
        await client.get(f"{BASE}/workspaces/{wid}/documents", headers=owner)
    ).json()["total"] == 0


async def test_supported_types_accepted(client: AsyncClient) -> None:
    owner = await _user(client, "owner@example.com")
    wid = await _workspace(client, owner, "acme")
    for name, data in (
        ("a.pdf", PDF),
        ("b.docx", _docx()),
        ("c.txt", TXT),
        ("d.md", b"# Heading\n"),
    ):
        response = await _upload(client, owner, wid, name, data)
        assert response.status_code == 201, (name, response.text)


async def test_duplicate_detection_is_per_workspace(client: AsyncClient) -> None:
    owner = await _user(client, "owner@example.com")
    wid_a = await _workspace(client, owner, "workspace-a")
    wid_b = await _workspace(client, owner, "workspace-b")

    first = await _upload(client, owner, wid_a, "one.txt", TXT)
    assert first.status_code == 201
    duplicate = await _upload(client, owner, wid_a, "renamed.txt", TXT)
    assert duplicate.status_code == 409
    assert duplicate.json()["error"]["code"] == "DUPLICATE_DOCUMENT"
    assert duplicate.json()["error"]["details"]["document_id"] == first.json()["id"]

    # Same bytes in a different workspace are allowed.
    other = await _upload(client, owner, wid_b, "one.txt", TXT)
    assert other.status_code == 201, other.text


async def test_role_rules(client: AsyncClient) -> None:
    owner = await _user(client, "owner@example.com")
    wid = await _workspace(client, owner, "acme")
    member = await _invite_and_accept(client, owner, wid, "member@example.com")
    admin = await _invite_and_accept(client, owner, wid, "admin@example.com", "admin")

    assert (await _upload(client, member, wid, "m.txt", TXT)).status_code == 403
    created = await _upload(client, admin, wid, "a.txt", TXT)
    assert created.status_code == 201
    document_id = created.json()["id"]

    # Members can read; only admins/owners delete.
    assert (
        await client.get(f"{BASE}/workspaces/{wid}/documents", headers=member)
    ).status_code == 200
    assert (
        await client.get(
            f"{BASE}/workspaces/{wid}/documents/{document_id}", headers=member
        )
    ).status_code == 200
    assert (
        await client.delete(
            f"{BASE}/workspaces/{wid}/documents/{document_id}", headers=member
        )
    ).status_code == 403
    assert (
        await client.delete(
            f"{BASE}/workspaces/{wid}/documents/{document_id}", headers=admin
        )
    ).status_code == 204


async def test_cross_tenant_access_denied(client: AsyncClient, fake_storage) -> None:
    a = await _user(client, "owner-a@example.com")
    b = await _user(client, "owner-b@example.com")
    wid_a = await _workspace(client, a, "workspace-a")
    wid_b = await _workspace(client, b, "workspace-b")

    uploaded = await _upload(client, b, wid_b, "secret.txt", b"secret data")
    assert uploaded.status_code == 201
    document_id = uploaded.json()["id"]

    # A cannot list, get, presign, delete, or upload into B's workspace.
    assert (
        await client.get(f"{BASE}/workspaces/{wid_b}/documents", headers=a)
    ).status_code == 403
    assert (
        await client.get(
            f"{BASE}/workspaces/{wid_b}/documents/{document_id}", headers=a
        )
    ).status_code == 403
    assert (
        await client.get(
            f"{BASE}/workspaces/{wid_b}/documents/{document_id}/url", headers=a
        )
    ).status_code == 403
    assert (
        await client.delete(
            f"{BASE}/workspaces/{wid_b}/documents/{document_id}", headers=a
        )
    ).status_code == 403
    assert (await _upload(client, a, wid_b, "stolen.txt", TXT)).status_code == 403

    # A only sees their own (empty) list, and B's file is still present.
    assert (await client.get(f"{BASE}/workspaces/{wid_a}/documents", headers=a)).json()[
        "total"
    ] == 0
    assert len(fake_storage.objects) == 1


async def test_deleting_document_cascades_to_chunks(session_factory) -> None:
    from sqlalchemy import select, text

    from core.security import hash_password
    from models import Document, DocumentChunk, DocumentStatus, User, Workspace

    async with session_factory() as session:
        user = User(email="cascade@example.com", password_hash=hash_password(PASSWORD))
        session.add(user)
        await session.flush()  # assign the generated user id
        workspace = Workspace(name="Cascade", slug="cascade", created_by=user.id)
        session.add(workspace)
        await session.flush()  # assign the generated workspace id
        document = Document(
            workspace_id=workspace.id,
            uploaded_by=user.id,
            filename="doc.txt",
            mime_type="text/plain",
            size=5,
            sha256="a" * 64,
            storage_key=f"{workspace.id}/key",
            status=DocumentStatus.READY,
        )
        chunk = DocumentChunk(
            workspace_id=workspace.id,
            document=document,
            chunk_index=0,
            content="hello",
        )
        session.add_all((document, chunk))
        await session.commit()
        document_id = document.id
        workspace_id = workspace.id

    async with session_factory() as session:
        loaded = await session.get(Document, document_id)
        assert loaded is not None
        await session.delete(loaded)
        await session.commit()

    async with session_factory() as session:
        remaining = (await session.execute(select(DocumentChunk))).scalars().all()
        assert remaining == []
        count = (
            await session.execute(
                text("SELECT count(*) FROM documents WHERE workspace_id = :wid"),
                {"wid": str(workspace_id)},
            )
        ).scalar_one()
        assert count == 0


async def test_unknown_document_is_404(client: AsyncClient) -> None:
    owner = await _user(client, "owner@example.com")
    wid = await _workspace(client, owner, "acme")
    missing = uuid4()
    for method, url in (
        ("GET", f"{BASE}/workspaces/{wid}/documents/{missing}"),
        ("GET", f"{BASE}/workspaces/{wid}/documents/{missing}/url"),
        ("DELETE", f"{BASE}/workspaces/{wid}/documents/{missing}"),
    ):
        response = await client.request(method, url, headers=owner)
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "DOCUMENT_NOT_FOUND"
