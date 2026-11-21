"""Phase 9 production hardening: limits, feedback, usage, audit, export, deletion."""

import uuid
from typing import cast

import pytest
from httpx import AsyncClient
from redis.asyncio import Redis
from redis.exceptions import RedisError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from api.v1.dependencies import get_redis_client
from core.config import get_settings
from core.rate_limit import (
    RateLimitUnavailableError,
    UserRateLimiter,
    UserRateLimitExceededError,
)
from main import app
from models import (
    AuditLog,
    Conversation,
    Document,
    DocumentStatus,
    Message,
    MessageFeedback,
    User,
    Workspace,
)

BASE = "/api/v1"
PASSWORD = "StrongPassw0rd!"
TXT = b"Hello, world!\n"


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


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


async def _seed_answers(
    factory: async_sessionmaker[AsyncSession],
    wid: str,
    email: str,
    *,
    questions: list[str] | None = None,
    answerable: bool = True,
) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID]:
    """Create a document + conversation with one Q/A pair.

    Returns (document_id, user_message_id, assistant_message_id).
    """
    questions = questions or ["what is alpha?"]
    async with factory() as session:
        user = (
            await session.execute(select(User).where(User.email == email))
        ).scalar_one()
        document = Document(
            workspace_id=uuid.UUID(wid),
            uploaded_by=user.id,
            filename="alpha.txt",
            mime_type="text/plain",
            size=len(TXT),
            sha256=uuid.uuid4().hex + uuid.uuid4().hex,
            storage_key=f"{wid}/{uuid.uuid4()}",
            status=DocumentStatus.READY,
        )
        session.add(document)
        await session.flush()
        conversation = Conversation(
            workspace_id=uuid.UUID(wid), user_id=user.id, title="Chat"
        )
        session.add(conversation)
        await session.flush()
        user_message = Message(
            conversation_id=conversation.id,
            sequence=0,
            role="user",
            content=questions[0],
            input_tokens=0,
            output_tokens=0,
        )
        assistant_message = Message(
            conversation_id=conversation.id,
            sequence=1,
            role="assistant",
            content="Grounded answer." if answerable else "I don't know",
            answerable=answerable,
            input_tokens=10,
            output_tokens=4,
            citations=[
                {
                    "document_id": str(document.id),
                    "filename": document.filename,
                    "chunk_id": str(uuid.uuid4()),
                }
            ],
        )
        session.add_all((user_message, assistant_message))
        await session.commit()
        return document.id, user_message.id, assistant_message.id


# ---------------------------------------------------------------------------
# rate limiting
# ---------------------------------------------------------------------------


async def test_user_rate_limiter_counts_and_rejects(fake_redis) -> None:
    limiter = UserRateLimiter(fake_redis, "chat", 2, 60)
    user_id = uuid.uuid4()
    await limiter.check(user_id)
    await limiter.check(user_id)
    with pytest.raises(UserRateLimitExceededError) as exc:
        await limiter.check(user_id)
    assert exc.value.status_code == 429
    assert exc.value.headers == {"Retry-After": "60"}
    # A different user has an independent counter.
    await limiter.check(uuid.uuid4())


async def test_user_rate_limiter_fails_closed() -> None:
    class BrokenRedis:
        async def eval(self, *_args, **_kwargs):
            raise RedisError("redis is down")

    limiter = UserRateLimiter(cast(Redis, BrokenRedis()), "chat", 2, 60)
    with pytest.raises(RateLimitUnavailableError):
        await limiter.check(uuid.uuid4())


async def test_upload_rate_limit_enforced_by_endpoint(
    client: AsyncClient, monkeypatch
) -> None:
    monkeypatch.setattr(get_settings(), "upload_rate_limit_max", 2)
    monkeypatch.setattr(get_settings(), "upload_rate_limit_window_seconds", 60)
    headers = await _user(client, "upload-limit@example.com")
    wid = await _workspace(client, headers, "upload-limit")
    url = f"{BASE}/workspaces/{wid}/documents"
    for name in ("a.txt", "b.txt"):
        response = await client.post(
            url,
            headers=headers,
            files={"file": (name, TXT + name.encode(), "text/plain")},
        )
        assert response.status_code == 201, response.text
    limited = await client.post(
        url,
        headers=headers,
        files={"file": ("c.txt", TXT + b"c.txt", "text/plain")},
    )
    assert limited.status_code == 429
    assert limited.json()["error"]["code"] == "USER_RATE_LIMIT_EXCEEDED"
    assert limited.headers["Retry-After"] == "60"


async def test_chat_rate_limit_enforced_by_endpoint(
    client: AsyncClient, monkeypatch
) -> None:
    monkeypatch.setattr(get_settings(), "chat_rate_limit_max", 0)
    monkeypatch.setattr(get_settings(), "chat_rate_limit_window_seconds", 60)
    headers = await _user(client, "chat-limit@example.com")
    wid = await _workspace(client, headers, "chat-limit")
    response = await client.post(
        f"{BASE}/workspaces/{wid}/chat/complete",
        headers=headers,
        json={"query": "what is alpha?"},
    )
    assert response.status_code == 429
    assert response.json()["error"]["code"] == "USER_RATE_LIMIT_EXCEEDED"
    assert response.headers["Retry-After"] == "60"


async def test_rate_limit_redis_outage_returns_503(
    client: AsyncClient, monkeypatch, fake_redis
) -> None:
    class BrokenRedis:
        async def eval(self, *_args, **_kwargs):
            raise RedisError("redis is down")

    headers = await _user(client, "outage@example.com")
    wid = await _workspace(client, headers, "outage")
    app.dependency_overrides[get_redis_client] = lambda: cast(Redis, BrokenRedis())
    try:
        response = await client.post(
            f"{BASE}/workspaces/{wid}/documents",
            headers=headers,
            files={"file": ("a.txt", TXT, "text/plain")},
        )
        assert response.status_code == 503
        assert response.json()["error"]["code"] == "RATE_LIMIT_UNAVAILABLE"
    finally:
        app.dependency_overrides[get_redis_client] = lambda: fake_redis


# ---------------------------------------------------------------------------
# feedback
# ---------------------------------------------------------------------------


async def test_feedback_upsert(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    headers = await _user(client, "feedback@example.com")
    wid = await _workspace(client, headers, "feedback")
    _, user_msg, assistant_msg = await _seed_answers(
        session_factory, wid, "feedback@example.com"
    )
    url = f"{BASE}/workspaces/{wid}/messages/{assistant_msg}/feedback"

    created = await client.post(
        url, headers=headers, json={"vote": "up", "comment": "great"}
    )
    assert created.status_code == 200, created.text
    assert created.json()["vote"] == "up"
    assert created.json()["comment"] == "great"

    updated = await client.post(
        url, headers=headers, json={"vote": "down", "comment": None}
    )
    assert updated.status_code == 200
    assert updated.json()["vote"] == "down"
    assert updated.json()["comment"] is None

    async with session_factory() as session:
        rows = (await session.execute(select(MessageFeedback))).scalars().all()
        assert len(rows) == 1  # upsert, not two rows
        assert rows[0].vote == "down"
        assert rows[0].message_id == assistant_msg

    # Feedback is only valid for assistant messages in this workspace.
    invalid = await client.post(
        f"{BASE}/workspaces/{wid}/messages/{user_msg}/feedback",
        headers=headers,
        json={"vote": "up"},
    )
    assert invalid.status_code == 404
    assert invalid.json()["error"]["code"] == "MESSAGE_NOT_FOUND"


async def test_feedback_is_tenant_isolated(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    a = await _user(client, "a-feedback@example.com")
    b = await _user(client, "b-feedback@example.com")
    wa = await _workspace(client, a, "feedback-a")
    wb = await _workspace(client, b, "feedback-b")
    _, _, assistant_msg = await _seed_answers(
        session_factory, wa, "a-feedback@example.com"
    )
    url = f"{BASE}/workspaces/{wa}/messages/{assistant_msg}/feedback"

    # B is not a member of A's workspace.
    denied = await client.post(url, headers=b, json={"vote": "up"})
    assert denied.status_code == 403
    # A cannot reach through B's workspace id to reach the message.
    denied = await client.post(
        f"{BASE}/workspaces/{wb}/messages/{assistant_msg}/feedback",
        headers=a,
        json={"vote": "up"},
    )
    assert denied.status_code == 403


# ---------------------------------------------------------------------------
# usage, analytics, audit log
# ---------------------------------------------------------------------------


async def test_usage_analytics_and_audit(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    headers = await _user(client, "usage@example.com")
    wid = await _workspace(client, headers, "usage")
    doc_id, _, assistant_msg = await _seed_answers(
        session_factory, wid, "usage@example.com"
    )
    # A second, low-confidence answer with a different question.
    await _seed_answers(
        session_factory,
        wid,
        "usage@example.com",
        questions=["what is beta?"],
        answerable=False,
    )
    # Feedback counts feed into usage totals.
    feedback = await client.post(
        f"{BASE}/workspaces/{wid}/messages/{assistant_msg}/feedback",
        headers=headers,
        json={"vote": "up"},
    )
    assert feedback.status_code == 200

    usage = await client.get(f"{BASE}/workspaces/{wid}/usage", headers=headers)
    assert usage.status_code == 200, usage.text
    body = usage.json()
    assert body["queries"] == 2
    assert body["answers"] == 2
    assert body["output_tokens"] == 28  # (10 input + 4 output) x 2 answers
    assert body["documents"] == 2
    assert body["storage_bytes"] == 2 * len(TXT)
    assert body["feedback_up"] == 1
    assert body["feedback_down"] == 0

    analytics = await client.get(
        f"{BASE}/workspaces/{wid}/usage/analytics", headers=headers
    )
    assert analytics.status_code == 200, analytics.text
    report = analytics.json()
    assert {item["question"] for item in report["most_asked"]} == {
        "what is alpha?",
        "what is beta?",
    }
    assert report["low_confidence_count"] == 1
    assert report["low_confidence_questions"] == [
        {"question": "what is beta?", "count": 1}
    ]
    assert report["most_cited"][0]["document_id"] == str(doc_id)

    log = await client.get(f"{BASE}/workspaces/{wid}/audit-log", headers=headers)
    assert log.status_code == 200, log.text
    assert isinstance(log.json(), list)


async def test_analytics_and_audit_require_admin(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    owner = await _user(client, "admin-owner@example.com")
    wid = await _workspace(client, owner, "admin-workspace")
    invite = await client.post(
        f"{BASE}/workspaces/{wid}/invitations",
        headers=owner,
        json={"email": "plain-member@example.com", "role": "member"},
    )
    assert invite.status_code == 201
    member = await _user(client, "plain-member@example.com")
    accepted = await client.post(
        f"{BASE}/invitations/accept",
        headers=member,
        json={"token": invite.json()["token"]},
    )
    assert accepted.status_code == 200

    for path in ("usage/analytics", "audit-log"):
        denied = await client.get(f"{BASE}/workspaces/{wid}/{path}", headers=member)
        assert denied.status_code == 403
        assert denied.json()["error"]["code"] == "INSUFFICIENT_ROLE"


async def test_upload_writes_audit_entry(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    headers = await _user(client, "audit@example.com")
    wid = await _workspace(client, headers, "audit")
    uploaded = await client.post(
        f"{BASE}/workspaces/{wid}/documents",
        headers=headers,
        files={"file": ("audit.txt", TXT, "text/plain")},
    )
    assert uploaded.status_code == 201, uploaded.text
    document_id = uploaded.json()["id"]

    log = await client.get(f"{BASE}/workspaces/{wid}/audit-log", headers=headers)
    assert log.status_code == 200
    entries = log.json()
    assert any(
        entry["action"] == "document.uploaded"
        and entry["target_id"] == document_id
        and entry["actor_email"] == "audit@example.com"
        for entry in entries
    )


# ---------------------------------------------------------------------------
# export & account deletion
# ---------------------------------------------------------------------------


async def test_workspace_export(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    headers = await _user(client, "export@example.com")
    wid = await _workspace(client, headers, "export")
    doc_id, _, _ = await _seed_answers(session_factory, wid, "export@example.com")

    exported = await client.get(f"{BASE}/workspaces/{wid}/export", headers=headers)
    assert exported.status_code == 200, exported.text
    assert "attachment;" in exported.headers["content-disposition"]
    data = exported.json()
    assert data["workspace"]["id"] == wid
    assert data["workspace"]["name"] == "export"
    assert [doc["id"] for doc in data["documents"]] == [str(doc_id)]
    assert len(data["conversations"]) == 1
    assert len(data["messages"]) == 2
    assert len(data["members"]) == 1

    log = await client.get(f"{BASE}/workspaces/{wid}/audit-log", headers=headers)
    assert any(entry["action"] == "workspace.exported" for entry in log.json())


async def test_account_deletion_removes_data_and_keeps_audit(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    fake_storage,
) -> None:
    headers = await _user(client, "delete@example.com")
    wid = await _workspace(client, headers, "delete")
    uploaded = await client.post(
        f"{BASE}/workspaces/{wid}/documents",
        headers=headers,
        files={"file": ("delete.txt", TXT, "text/plain")},
    )
    assert uploaded.status_code == 201
    assert fake_storage.objects  # a file was stored

    deleted = await client.delete(f"{BASE}/account", headers=headers)
    assert deleted.status_code == 204, deleted.text
    assert not fake_storage.objects

    async with session_factory() as session:
        assert (
            await session.execute(
                select(User).where(User.email == "delete@example.com")
            )
        ).scalar_one_or_none() is None
        assert (
            await session.execute(
                select(Workspace).where(Workspace.id == uuid.UUID(wid))
            )
        ).scalar_one_or_none() is None
        assert (
            await session.execute(
                select(Document).where(Document.workspace_id == uuid.UUID(wid))
            )
        ).scalars().all() == []
        # The audit trail survives account deletion, with the actor preserved.
        audit = (
            (
                await session.execute(
                    select(AuditLog).where(AuditLog.actor_email == "delete@example.com")
                )
            )
            .scalars()
            .all()
        )
        assert any(entry.action == "account.deleted" for entry in audit)

    # The deleted user's token no longer authenticates.
    later = await client.get(f"{BASE}/workspaces", headers=headers)
    assert later.status_code == 401


# ---------------------------------------------------------------------------
# security headers
# ---------------------------------------------------------------------------


async def test_security_headers_on_every_response(client: AsyncClient) -> None:
    response = await client.get(f"{BASE}/ping")
    assert response.status_code == 200
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"
    assert response.headers["referrer-policy"] == "no-referrer"
    assert "default-src 'none'" in response.headers["content-security-policy"]
    assert response.headers["cross-origin-opener-policy"] == "same-origin"
    # The test client uses https, so HSTS is present too.
    assert "max-age=31536000" in response.headers["strict-transport-security"]
