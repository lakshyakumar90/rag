"""End-to-end workspace, membership and invitation tests."""

from datetime import UTC, datetime, timedelta

from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from core.security import hash_token

BASE = "/api/v1"
STRONG_PASSWORD = "StrongPassw0rd!"


async def _user(client: AsyncClient, email: str) -> dict[str, str]:
    """Register a user and return Bearer headers for their access token."""
    registered = await client.post(
        f"{BASE}/auth/register",
        json={"email": email, "password": STRONG_PASSWORD},
    )
    assert registered.status_code == 201, registered.text
    login = await client.post(
        f"{BASE}/auth/login", json={"email": email, "password": STRONG_PASSWORD}
    )
    assert login.status_code == 200, login.text
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


async def _create(
    client: AsyncClient, headers: dict[str, str], slug: str = "acme"
) -> dict:
    response = await client.post(
        f"{BASE}/workspaces",
        headers=headers,
        json={"name": "Acme Corp", "slug": slug},
    )
    assert response.status_code == 201, response.text
    return response.json()


async def _invite(
    client: AsyncClient, headers: dict[str, str], workspace_id: str, email: str
) -> dict:
    response = await client.post(
        f"{BASE}/workspaces/{workspace_id}/invitations",
        headers=headers,
        json={"email": email, "role": "member"},
    )
    assert response.status_code == 201, response.text
    return response.json()


async def test_create_workspace_makes_creator_owner(client: AsyncClient) -> None:
    headers = await _user(client, "owner@example.com")
    workspace = await _create(client, headers)

    assert workspace["name"] == "Acme Corp"
    assert workspace["slug"] == "acme"
    assert workspace["my_role"] == "owner"

    listed = await client.get(f"{BASE}/workspaces", headers=headers)
    assert listed.status_code == 200
    assert [item["id"] for item in listed.json()] == [workspace["id"]]

    fetched = await client.get(f"{BASE}/workspaces/{workspace['id']}", headers=headers)
    assert fetched.status_code == 200
    assert fetched.json()["my_role"] == "owner"


async def test_duplicate_slug_rejected(client: AsyncClient) -> None:
    headers = await _user(client, "owner@example.com")
    await _create(client, headers)
    response = await client.post(
        f"{BASE}/workspaces",
        headers=headers,
        json={"name": "Other", "slug": "ACME"},
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "WORKSPACE_SLUG_EXISTS"


async def test_non_member_cannot_access_workspace(client: AsyncClient) -> None:
    owner = await _user(client, "owner@example.com")
    outsider = await _user(client, "outsider@example.com")
    workspace = await _create(client, owner)

    response = await client.get(
        f"{BASE}/workspaces/{workspace['id']}", headers=outsider
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "NOT_WORKSPACE_MEMBER"


async def test_update_and_delete_are_owner_only(client: AsyncClient) -> None:
    owner = await _user(client, "owner@example.com")
    member_headers = await _user(client, "member@example.com")
    workspace = await _create(client, owner)
    invitation = await _invite(client, owner, workspace["id"], "member@example.com")
    accepted = await client.post(
        f"{BASE}/invitations/accept",
        headers=member_headers,
        json={"token": invitation["token"]},
    )
    assert accepted.status_code == 200

    forbidden = await client.patch(
        f"{BASE}/workspaces/{workspace['id']}",
        headers=member_headers,
        json={"name": "Hacked"},
    )
    assert forbidden.status_code == 403
    assert forbidden.json()["error"]["code"] == "OWNER_REQUIRED"

    updated = await client.patch(
        f"{BASE}/workspaces/{workspace['id']}",
        headers=owner,
        json={"name": "New Name", "slug": "new-slug"},
    )
    assert updated.status_code == 200
    assert updated.json()["name"] == "New Name"
    assert updated.json()["slug"] == "new-slug"

    deleted = await client.delete(f"{BASE}/workspaces/{workspace['id']}", headers=owner)
    assert deleted.status_code == 204
    listed = await client.get(f"{BASE}/workspaces", headers=member_headers)
    assert listed.json() == []


async def test_invite_and_accept(client: AsyncClient) -> None:
    owner = await _user(client, "owner@example.com")
    invitee = await _user(client, "invitee@example.com")
    workspace = await _create(client, owner)

    invitation = await _invite(client, owner, workspace["id"], "invitee@example.com")
    assert invitation["token"]
    assert invitation["accept_url"].endswith(invitation["token"])
    assert "token_hash" not in invitation
    assert invitation["role"] == "member"
    assert invitation["status"] == "pending"

    invitations = await client.get(
        f"{BASE}/workspaces/{workspace['id']}/invitations", headers=owner
    )
    assert invitations.status_code == 200
    assert len(invitations.json()) == 1
    assert "token" not in invitations.json()[0]

    accepted = await client.post(
        f"{BASE}/invitations/accept",
        headers=invitee,
        json={"token": invitation["token"]},
    )
    assert accepted.status_code == 200
    assert accepted.json()["my_role"] == "member"
    assert accepted.json()["id"] == workspace["id"]

    members = await client.get(
        f"{BASE}/workspaces/{workspace['id']}/members", headers=owner
    )
    assert members.status_code == 200
    assert {item["email"]: item["role"] for item in members.json()} == {
        "owner@example.com": "owner",
        "invitee@example.com": "member",
    }


async def test_accept_rejects_wrong_email_reuse_and_expiry(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    owner = await _user(client, "owner@example.com")
    stranger = await _user(client, "stranger@example.com")
    workspace = await _create(client, owner)
    invitation = await _invite(client, owner, workspace["id"], "invitee@example.com")

    wrong_email = await client.post(
        f"{BASE}/invitations/accept",
        headers=stranger,
        json={"token": invitation["token"]},
    )
    assert wrong_email.status_code == 403
    assert wrong_email.json()["error"]["code"] == "INVITATION_EMAIL_MISMATCH"

    invitee = await _user(client, "invitee@example.com")
    accepted = await client.post(
        f"{BASE}/invitations/accept",
        headers=invitee,
        json={"token": invitation["token"]},
    )
    assert accepted.status_code == 200

    reused = await client.post(
        f"{BASE}/invitations/accept",
        headers=invitee,
        json={"token": invitation["token"]},
    )
    assert reused.status_code == 409
    assert reused.json()["error"]["code"] == "INVITATION_UNAVAILABLE"

    second = await _invite(client, owner, workspace["id"], "late@example.com")
    async with session_factory() as session:
        await session.execute(
            text("UPDATE invitations SET expires_at = :past WHERE token_hash = :hash"),
            {
                "past": (datetime.now(UTC) - timedelta(days=1)).isoformat(),
                "hash": hash_token(second["token"]),
            },
        )
        await session.commit()
    late = await _user(client, "late@example.com")
    expired = await client.post(
        f"{BASE}/invitations/accept",
        headers=late,
        json={"token": second["token"]},
    )
    assert expired.status_code == 410
    assert expired.json()["error"]["code"] == "INVITATION_EXPIRED"


async def test_unknown_token_rejected(client: AsyncClient) -> None:
    headers = await _user(client, "user@example.com")
    response = await client.post(
        f"{BASE}/invitations/accept", headers=headers, json={"token": "not-a-token"}
    )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "INVITATION_NOT_FOUND"


async def test_member_cannot_invite(client: AsyncClient) -> None:
    owner = await _user(client, "owner@example.com")
    member_headers = await _user(client, "member@example.com")
    workspace = await _create(client, owner)
    invitation = await _invite(client, owner, workspace["id"], "member@example.com")
    await client.post(
        f"{BASE}/invitations/accept",
        headers=member_headers,
        json={"token": invitation["token"]},
    )

    response = await client.post(
        f"{BASE}/workspaces/{workspace['id']}/invitations",
        headers=member_headers,
        json={"email": "other@example.com", "role": "member"},
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "OWNER_REQUIRED"


async def test_change_role_and_remove_member(client: AsyncClient) -> None:
    owner = await _user(client, "owner@example.com")
    member_headers = await _user(client, "member@example.com")
    workspace = await _create(client, owner)
    invitation = await _invite(client, owner, workspace["id"], "member@example.com")
    await client.post(
        f"{BASE}/invitations/accept",
        headers=member_headers,
        json={"token": invitation["token"]},
    )
    user_id = next(
        item["user_id"]
        for item in (
            await client.get(
                f"{BASE}/workspaces/{workspace['id']}/members", headers=owner
            )
        ).json()
        if item["email"] == "member@example.com"
    )

    promoted = await client.patch(
        f"{BASE}/workspaces/{workspace['id']}/members/{user_id}",
        headers=owner,
        json={"role": "admin"},
    )
    assert promoted.status_code == 200
    assert promoted.json()["role"] == "admin"

    removed = await client.delete(
        f"{BASE}/workspaces/{workspace['id']}/members/{user_id}", headers=owner
    )
    assert removed.status_code == 204

    gone = await client.get(
        f"{BASE}/workspaces/{workspace['id']}", headers=member_headers
    )
    assert gone.status_code == 403


async def test_last_owner_cannot_be_demoted_or_removed(client: AsyncClient) -> None:
    owner = await _user(client, "owner@example.com")
    workspace = await _create(client, owner)
    owner_id = next(
        item["user_id"]
        for item in (
            await client.get(
                f"{BASE}/workspaces/{workspace['id']}/members", headers=owner
            )
        ).json()
        if item["email"] == "owner@example.com"
    )

    demote = await client.patch(
        f"{BASE}/workspaces/{workspace['id']}/members/{owner_id}",
        headers=owner,
        json={"role": "member"},
    )
    assert demote.status_code == 409
    assert demote.json()["error"]["code"] == "LAST_OWNER"

    remove = await client.delete(
        f"{BASE}/workspaces/{workspace['id']}/members/{owner_id}", headers=owner
    )
    assert remove.status_code == 409
    assert remove.json()["error"]["code"] == "LAST_OWNER"

    # With two owners, demoting one is allowed.
    second_headers = await _user(client, "second@example.com")
    invitation = await _invite(client, owner, workspace["id"], "second@example.com")
    await client.post(
        f"{BASE}/invitations/accept",
        headers=second_headers,
        json={"token": invitation["token"]},
    )
    second_id = next(
        item["user_id"]
        for item in (
            await client.get(
                f"{BASE}/workspaces/{workspace['id']}/members", headers=owner
            )
        ).json()
        if item["email"] == "second@example.com"
    )
    promote = await client.patch(
        f"{BASE}/workspaces/{workspace['id']}/members/{second_id}",
        headers=owner,
        json={"role": "owner"},
    )
    assert promote.status_code == 200

    demote_first = await client.patch(
        f"{BASE}/workspaces/{workspace['id']}/members/{owner_id}",
        headers=owner,
        json={"role": "member"},
    )
    assert demote_first.status_code == 200
