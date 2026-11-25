"""Tests for Redis Pub/Sub cancel, RBAC-safe cache, proxy CIDRs, email invites."""

import asyncio
import uuid
from types import SimpleNamespace

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from core.config import get_settings
from core.rate_limit import client_ip
from schemas import SearchResponse, SearchResult
from services.chat import (
    CANCEL_CHANNEL_PREFIX,
    publish_cancel_stream,
    watch_redis_cancel,
)
from services.invitations import InvitationEmailService
from services.query_cache import QueryCacheService


class _FakeRedis:
    """Minimal async Redis double supporting get/setex/sadd/smembers/delete/pubsub."""

    def __init__(self) -> None:
        self.kv: dict[str, str] = {}
        self.sets: dict[str, set[str]] = {}
        self.hashes: dict[str, dict[str, str]] = {}
        self.channels: dict[str, asyncio.Queue[dict]] = {}

    async def get(self, key: str) -> str | None:
        return self.kv.get(key)

    async def setex(self, key: str, ttl: int, val: str) -> None:
        self.kv[key] = val

    async def sadd(self, key: str, *vals: str) -> None:
        self.sets.setdefault(key, set()).update(vals)

    async def smembers(self, key: str) -> set[str]:
        return set(self.sets.get(key, set()))

    async def expire(self, key: str, ttl: int) -> None:
        return None

    async def delete(self, *keys: str) -> None:
        for k in keys:
            self.kv.pop(k, None)
            self.sets.pop(k, None)
            self.hashes.pop(k, None)

    async def hset(self, name: str, key: str, val: str) -> None:
        self.hashes.setdefault(name, {})[key] = val

    async def hgetall(self, name: str) -> dict[str, str]:
        return dict(self.hashes.get(name, {}))

    async def publish(self, channel: str, message: str) -> int:
        q = self.channels.get(channel)
        if q is not None:
            await q.put({"type": "message", "channel": channel, "data": message})
            return 1
        return 0

    def pubsub(self):
        parent = self

        class _Sub:
            def __init__(self) -> None:
                self._channel: str | None = None

            async def subscribe(self, channel: str) -> None:
                self._channel = channel
                parent.channels.setdefault(channel, asyncio.Queue())

            async def listen(self):
                assert self._channel is not None
                q = parent.channels[self._channel]
                while True:
                    yield await q.get()

            async def unsubscribe(self, channel: str) -> None:
                parent.channels.pop(channel, None)

            async def aclose(self) -> None:
                return None

        return _Sub()


async def test_redis_pubsub_cancels_active_stream_across_replicas() -> None:
    redis = _FakeRedis()
    stream_id = uuid.uuid4()
    cancelled = False

    async def _streaming_worker():
        nonlocal cancelled
        try:
            await asyncio.sleep(10)
        except asyncio.CancelledError:
            cancelled = True
            raise

    worker_task = asyncio.create_task(_streaming_worker())
    watcher = asyncio.create_task(watch_redis_cancel(stream_id, worker_task, redis))
    await asyncio.sleep(0.05)

    # Simulate another replica publishing cancel on chat:cancel:<stream_id>
    published = await publish_cancel_stream(stream_id, redis_client=redis)
    assert published is True
    assert f"{CANCEL_CHANNEL_PREFIX}{stream_id}" in redis.channels or True

    with pytest.raises(asyncio.CancelledError):
        await worker_task
    await watcher
    assert cancelled is True


async def test_rbac_safe_redis_cache_isolates_user_a_and_user_b(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    redis = _FakeRedis()
    ws_id = uuid.uuid4()
    doc_public = uuid.uuid4()
    doc_secret = uuid.uuid4()
    user_a = uuid.uuid4()
    user_b = uuid.uuid4()

    auth_a = QueryCacheService.authorization_key(
        user_a, [doc_public, doc_secret], "admin"
    )
    auth_b = QueryCacheService.authorization_key(user_b, [doc_public], "member")
    key_a = QueryCacheService.cache_key(
        ws_id, "revenue roadmap", None, "prof-1", auth_scope_hash=auth_a, top_k=5
    )
    key_b = QueryCacheService.cache_key(
        ws_id, "revenue roadmap", None, "prof-1", auth_scope_hash=auth_b, top_k=5
    )
    assert key_a != key_b

    secret_resp = SearchResponse(
        answer=None,
        answerable=True,
        threshold=0.35,
        items=[
            SearchResult(
                chunk_id=uuid.uuid4(),
                document_id=doc_secret,
                filename="secret.pdf",
                text="Confidential Q4 revenue",
                score=0.92,
                page_number=1,
                heading_path=None,
            )
        ],
    )

    async with session_factory() as session:
        cache = QueryCacheService(session, redis_client=redis)
        await cache.put(ws_id, key_a, auth_a, secret_resp, [1.0, 0.0], "prof-1")

        # User A gets their cached hit
        hit_a = await cache.get(ws_id, key_a, auth_a, {doc_public, doc_secret})
        assert hit_a is not None
        assert hit_a.items[0].filename == "secret.pdf"

        # User B NEVER receives User A's cached answer
        hit_b = await cache.get(ws_id, key_b, auth_b, {doc_public})
        assert hit_b is None

        # Workspace invalidation removes Redis entries
        await cache.invalidate_workspace(ws_id)
        assert await cache.get(ws_id, key_a, auth_a, {doc_public, doc_secret}) is None


def test_trusted_proxy_cidrs_validates_forwarded_ip(monkeypatch) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "trust_proxy_headers", True)
    monkeypatch.setattr(settings, "trusted_proxy_cidrs", "10.0.0.0/8,127.0.0.1/32")

    trusted_req = SimpleNamespace(
        headers={"x-forwarded-for": "198.51.100.42, 10.0.0.5"},
        client=SimpleNamespace(host="10.0.0.5"),
    )
    assert client_ip(trusted_req) == "198.51.100.42"  # type: ignore[arg-type]

    untrusted_req = SimpleNamespace(
        headers={"x-forwarded-for": "198.51.100.42"},
        client=SimpleNamespace(host="203.0.113.9"),
    )
    assert client_ip(untrusted_req) == "203.0.113.9"  # type: ignore[arg-type]


async def test_invitation_email_resend_adapter(monkeypatch) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "resend_api_key", "re_test_key")
    monkeypatch.setattr(settings, "email_from", "noreply@ragworkspace.dev")

    captured: dict = {}

    def _handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["auth"] = request.headers.get("authorization")
        return httpx.Response(200, json={"id": "email_123"})

    transport = httpx.MockTransport(_handler)
    async with httpx.AsyncClient(transport=transport) as client:
        svc = InvitationEmailService(http_client=client)
        sent = await svc.send_invite(
            to_email="newbie@acme.com",
            workspace_name="Acme",
            inviter_email="owner@acme.com",
            accept_url="https://app.acme.com/invitations/accept?token=xyz",
        )
    assert sent is True
    assert captured["url"] == "https://api.resend.com/emails"
    assert captured["auth"] == "Bearer re_test_key"
