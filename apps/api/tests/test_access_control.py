"""Tenant isolation and role-check tests.

User A owns workspace A; user B owns workspace B. A must not be able to read,
list, or modify anything in B through any endpoint, and role checks must hold
inside A.
"""

from uuid import uuid4

from httpx import AsyncClient

BASE = "/api/v1"
PASSWORD = "StrongPassw0rd!"


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


async def _workspace(
    client: AsyncClient, headers: dict[str, str], name: str, slug: str
) -> dict:
    created = await client.post(
        f"{BASE}/workspaces", headers=headers, json={"name": name, "slug": slug}
    )
    assert created.status_code == 201, created.text
    return created.json()


async def _invite(
    client: AsyncClient,
    headers: dict[str, str],
    workspace_id: str,
    email: str,
    role: str = "member",
) -> dict:
    created = await client.post(
        f"{BASE}/workspaces/{workspace_id}/invitations",
        headers=headers,
        json={"email": email, "role": role},
    )
    assert created.status_code == 201, created.text
    return created.json()


async def _accept(client: AsyncClient, headers: dict[str, str], token: str) -> None:
    accepted = await client.post(
        f"{BASE}/invitations/accept", headers=headers, json={"token": token}
    )
    assert accepted.status_code == 200, accepted.text


async def _assert_forbidden(
    client: AsyncClient,
    method: str,
    url: str,
    headers: dict[str, str],
    *,
    code: str = "NOT_WORKSPACE_MEMBER",
    json: dict | None = None,
) -> None:
    response = await client.request(method, url, headers=headers, json=json)
    assert response.status_code == 403, (url, response.status_code, response.text)
    assert response.json()["error"]["code"] == code, (url, response.text)


async def _member_id(
    client: AsyncClient, headers: dict[str, str], workspace_id: str, email: str
) -> str:
    members = await client.get(
        f"{BASE}/workspaces/{workspace_id}/members", headers=headers
    )
    assert members.status_code == 200
    return next(item["user_id"] for item in members.json() if item["email"] == email)


async def test_tenant_isolation_covers_every_endpoint(client: AsyncClient) -> None:
    a = await _user(client, "owner-a@example.com")
    b = await _user(client, "owner-b@example.com")
    workspace_a = await _workspace(client, a, "Workspace A", "workspace-a")
    workspace_b = await _workspace(client, b, "Workspace B", "workspace-b")
    wa, wb = workspace_a["id"], workspace_b["id"]

    # An invitation that belongs to B; A must not be able to redeem it.
    invite_b = await _invite(client, b, wb, "invitee-b@example.com")
    b_member_id = await _member_id(client, b, wb, "owner-b@example.com")

    # 1. list: A only sees A's workspace.
    listed = await client.get(f"{BASE}/workspaces", headers=a)
    assert listed.status_code == 200
    assert [item["id"] for item in listed.json()] == [wa]

    # 2. get / update / delete a workspace in B.
    await _assert_forbidden(client, "GET", f"{BASE}/workspaces/{wb}", a)
    await _assert_forbidden(
        client, "PATCH", f"{BASE}/workspaces/{wb}", a, json={"name": "stolen"}
    )
    await _assert_forbidden(client, "DELETE", f"{BASE}/workspaces/{wb}", a)

    # 3. invitations in B (create, list).
    await _assert_forbidden(
        client,
        "POST",
        f"{BASE}/workspaces/{wb}/invitations",
        a,
        json={"email": "x@example.com", "role": "member"},
    )
    await _assert_forbidden(client, "GET", f"{BASE}/workspaces/{wb}/invitations", a)

    # 4. members in B (list, change role, remove).
    await _assert_forbidden(client, "GET", f"{BASE}/workspaces/{wb}/members", a)
    await _assert_forbidden(
        client,
        "PATCH",
        f"{BASE}/workspaces/{wb}/members/{b_member_id}",
        a,
        json={"role": "member"},
    )
    await _assert_forbidden(
        client, "DELETE", f"{BASE}/workspaces/{wb}/members/{b_member_id}", a
    )

    # 5. accept: A cannot redeem B's invitation (wrong email).
    wrong_email = await client.post(
        f"{BASE}/invitations/accept", headers=a, json={"token": invite_b["token"]}
    )
    assert wrong_email.status_code == 403
    assert wrong_email.json()["error"]["code"] == "INVITATION_EMAIL_MISMATCH"

    # 6. B's data is untouched by all of the above.
    still_there = await client.get(f"{BASE}/workspaces/{wb}", headers=b)
    assert still_there.status_code == 200
    assert still_there.json()["name"] == "Workspace B"
    members = await client.get(f"{BASE}/workspaces/{wb}/members", headers=b)
    assert len(members.json()) == 1
    invites = await client.get(f"{BASE}/workspaces/{wb}/invitations", headers=b)
    assert len(invites.json()) == 1
    assert invites.json()[0]["status"] == "pending"


async def test_target_from_other_workspace_is_not_a_member(client: AsyncClient) -> None:
    a = await _user(client, "owner-a@example.com")
    b = await _user(client, "owner-b@example.com")
    workspace_a = await _workspace(client, a, "Workspace A", "workspace-a")
    await _workspace(client, b, "Workspace B", "workspace-b")
    b_member_id = await _member_id(
        client, b, await _workspace_id(client, b), "owner-b@example.com"
    )

    # A's workspace has only A as a member; B's user id is not one of them.
    for method, url, json in (
        (
            "PATCH",
            f"{BASE}/workspaces/{workspace_a['id']}/members/{b_member_id}",
            {"role": "member"},
        ),
        (
            "DELETE",
            f"{BASE}/workspaces/{workspace_a['id']}/members/{b_member_id}",
            None,
        ),
    ):
        response = await client.request(method, url, headers=a, json=json)
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "MEMBER_NOT_FOUND"


async def _workspace_id(client: AsyncClient, headers: dict[str, str]) -> str:
    listed = await client.get(f"{BASE}/workspaces", headers=headers)
    assert listed.status_code == 200 and len(listed.json()) == 1
    return listed.json()[0]["id"]


async def test_role_checks_owner_only_actions(client: AsyncClient) -> None:
    owner = await _user(client, "owner@example.com")
    member_headers = await _user(client, "member@example.com")
    workspace = await _workspace(client, owner, "Acme", "acme")
    wid = workspace["id"]
    invite = await _invite(client, owner, wid, "member@example.com")
    await _accept(client, member_headers, invite["token"])
    member_id = await _member_id(client, owner, wid, "member@example.com")

    # A member may read.
    assert (
        await client.get(f"{BASE}/workspaces/{wid}", headers=member_headers)
    ).status_code == 200
    assert (
        await client.get(f"{BASE}/workspaces/{wid}/members", headers=member_headers)
    ).status_code == 200
    assert (
        await client.get(f"{BASE}/workspaces/{wid}/invitations", headers=member_headers)
    ).status_code == 200

    for method, url, json in (
        ("PATCH", f"{BASE}/workspaces/{wid}", {"name": "hacked"}),
        ("DELETE", f"{BASE}/workspaces/{wid}", None),
        ("PATCH", f"{BASE}/workspaces/{wid}/members/{member_id}", {"role": "owner"}),
        ("DELETE", f"{BASE}/workspaces/{wid}/members/{member_id}", None),
    ):
        await _assert_forbidden(
            client, method, url, member_headers, code="OWNER_REQUIRED", json=json
        )


async def test_admin_can_invite_but_not_manage_workspace_or_members(
    client: AsyncClient,
) -> None:
    owner = await _user(client, "owner@example.com")
    admin_headers = await _user(client, "admin@example.com")
    workspace = await _workspace(client, owner, "Acme", "acme")
    wid = workspace["id"]
    invite = await _invite(client, owner, wid, "admin@example.com", role="admin")
    await _accept(client, admin_headers, invite["token"])
    admin_id = await _member_id(client, owner, wid, "admin@example.com")

    # Admin can invite (and read).
    created = await client.post(
        f"{BASE}/workspaces/{wid}/invitations",
        headers=admin_headers,
        json={"email": "invited-by-admin@example.com", "role": "member"},
    )
    assert created.status_code == 201, created.text

    for method, url, json in (
        ("PATCH", f"{BASE}/workspaces/{wid}", {"name": "hacked"}),
        ("DELETE", f"{BASE}/workspaces/{wid}", None),
        ("PATCH", f"{BASE}/workspaces/{wid}/members/{admin_id}", {"role": "owner"}),
        ("DELETE", f"{BASE}/workspaces/{wid}/members/{admin_id}", None),
    ):
        await _assert_forbidden(
            client, method, url, admin_headers, code="OWNER_REQUIRED", json=json
        )


async def test_unknown_workspace_returns_404(client: AsyncClient) -> None:
    headers = await _user(client, "user@example.com")
    missing = uuid4()
    response = await client.get(f"{BASE}/workspaces/{missing}", headers=headers)
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "WORKSPACE_NOT_FOUND"
