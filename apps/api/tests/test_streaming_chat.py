"""Tests for SSE chat streaming, cancellation, regeneration and usage."""

import asyncio
import json
import uuid

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

import services.chat as chat_module
import services.conversations as conversations_module
from api.v1.dependencies import get_embedding_provider
from core.config import get_settings
from main import app
from models import Document, DocumentChunk, DocumentStatus, Message, User
from providers.llm.types import Completion, Finish, TextDelta, Usage
from services.chat import cancel_stream

PASSWORD = "StrongPassw0rd!"


class FakeStreamingLLM:
    def __init__(self, answer: str = "Grounded [1].", usage: Usage | None = None):
        self.answer = answer
        self.usage = usage
        self.stream_calls = 0
        self.complete_calls = 0

    async def stream(self, messages, **opts):
        self.stream_calls += 1
        half = len(self.answer) // 2
        yield TextDelta(self.answer[:half])
        yield TextDelta(self.answer[half:])
        if self.usage:
            yield self.usage
        yield Finish("stop")

    async def complete(self, messages, **opts):
        self.complete_calls += 1
        system = messages[0].content
        if system.startswith("Rewrite"):
            return Completion("alpha standalone", "stop", Usage(2, 1))
        if system.startswith("Write a short title"):
            return Completion("Alpha chat", "stop", Usage(2, 1))
        return Completion(self.answer, "stop", Usage(5, 2))

    async def close(self):
        return None


class KeywordEmbeddings:
    async def embed_documents(self, texts):
        return [await self.embed_query(text) for text in texts]

    async def embed_query(self, text):
        return [1.0, 0.0] if "alpha" in text.lower() else [0.0, 1.0]


def _parse_sse(text: str) -> list[dict]:
    return [
        json.loads(line[6:]) for line in text.splitlines() if line.startswith("data: ")
    ]


async def _login(client: AsyncClient, email: str) -> dict[str, str]:
    await client.post(
        "/api/v1/auth/register", json={"email": email, "password": PASSWORD}
    )
    login = await client.post(
        "/api/v1/auth/login", json={"email": email, "password": PASSWORD}
    )
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


async def _setup(client, factory, monkeypatch, llm):
    monkeypatch.setattr(chat_module, "create_llm_provider", lambda name: llm)
    monkeypatch.setattr(conversations_module, "create_llm_provider", lambda name: llm)
    monkeypatch.setattr(get_settings(), "llm_provider", "fake")
    headers = await _login(client, "stream@example.com")
    wid = (
        await client.post(
            "/api/v1/workspaces", headers=headers, json={"name": "Acme", "slug": "acme"}
        )
    ).json()["id"]
    app.dependency_overrides[get_embedding_provider] = lambda: KeywordEmbeddings()
    async with factory() as session:
        user = (await session.execute(select(User))).scalar_one()
        document = Document(
            workspace_id=uuid.UUID(wid),
            uploaded_by=user.id,
            filename="a.txt",
            mime_type="text/plain",
            size=5,
            sha256="a" * 64,
            storage_key=f"{wid}/key",
            status=DocumentStatus.READY,
        )
        session.add(document)
        await session.flush()
        session.add(
            DocumentChunk(
                document_id=document.id,
                workspace_id=uuid.UUID(wid),
                chunk_index=0,
                content="alpha",
                embedding=[1.0, 0.0],
                search_vector="alpha",
            )
        )
        await session.commit()
    return headers, wid


async def test_stream_events_and_persistence(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch,
) -> None:
    llm = FakeStreamingLLM()
    headers, wid = await _setup(client, session_factory, monkeypatch, llm)
    try:
        conversation_id = (
            await client.post(
                f"/api/v1/workspaces/{wid}/conversations", headers=headers, json={}
            )
        ).json()["id"]
        response = await client.post(
            f"/api/v1/workspaces/{wid}/chat",
            headers=headers,
            json={"query": "alpha", "conversation_id": conversation_id},
        )
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        events = _parse_sse(response.text)
        assert [event["type"] for event in events] == [
            "sources",
            "token",
            "token",
            "confidence",
            "done",
        ]
        assert events[0]["sources"][0]["filename"] == "a.txt"
        assert (
            "".join(e["text"] for e in events if e["type"] == "token")
            == "Grounded [1]."
        )
        done = events[-1]
        assert done["answerable"] is True
        assert len(done["citations"]) == 1
        assert done["tokens"]["estimated"] is True
        assert done["conversation_id"] == conversation_id

        messages = await client.get(
            f"/api/v1/workspaces/{wid}/conversations/{conversation_id}/messages",
            headers=headers,
        )
        body = messages.json()
        assert [item["role"] for item in body] == ["user", "assistant"]
        assert body[1]["content"] == "Grounded [1]."
        assert body[1]["tokens_estimated"] is True
        assert body[1]["output_tokens"] > 0
    finally:
        app.dependency_overrides.pop(get_embedding_provider, None)


async def test_stream_with_provider_usage(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch,
) -> None:
    llm = FakeStreamingLLM(usage=Usage(11, 5))
    headers, wid = await _setup(client, session_factory, monkeypatch, llm)
    try:
        response = await client.post(
            f"/api/v1/workspaces/{wid}/chat", headers=headers, json={"query": "alpha"}
        )
        done = _parse_sse(response.text)[-1]
        assert done["tokens"] == {"input": 11, "output": 5, "estimated": False}
    finally:
        app.dependency_overrides.pop(get_embedding_provider, None)


async def test_disconnect_persists_partial_answer(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch,
) -> None:
    llm = FakeStreamingLLM()
    headers, wid = await _setup(client, session_factory, monkeypatch, llm)
    try:
        conversation_id = uuid.UUID(
            (
                await client.post(
                    f"/api/v1/workspaces/{wid}/conversations", headers=headers, json={}
                )
            ).json()["id"]
        )
        from models import Workspace
        from services import ChatService, ConversationService, RetrievalService
        from services.workspaces import WorkspaceContext

        async with session_factory() as session:
            user = (await session.execute(select(User))).scalar_one()
            workspace = (await session.execute(select(Workspace))).scalar_one()
            context = WorkspaceContext(user=user, workspace=workspace, role="member")
            service = ChatService(
                RetrievalService(session, KeywordEmbeddings(), None),
                ConversationService(session),
            )
            state = {"checks": 0}

            async def disconnected() -> bool:
                state["checks"] += 1
                return state["checks"] >= 3  # allow sources + first token

            events = [
                event
                async for event in service.stream_answer(
                    context,
                    "alpha",
                    conversation_id=conversation_id,
                    is_disconnected=disconnected,
                )
            ]
            assert any(event["type"] == "token" for event in events)
            assert not any(event["type"] == "done" for event in events)

        async with session_factory() as session:
            stored = (
                (
                    await session.execute(
                        select(Message).where(
                            Message.conversation_id == conversation_id
                        )
                    )
                )
                .scalars()
                .all()
            )
            assert [message.role for message in stored] == ["user", "assistant"]
            # The partial answer (a prefix of the full one) is persisted.
            assert stored[-1].content.startswith("Ground")
    finally:
        app.dependency_overrides.pop(get_embedding_provider, None)


async def test_stop_cancel_and_regenerate_and_rename(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch,
) -> None:
    llm = FakeStreamingLLM()
    headers, wid = await _setup(client, session_factory, monkeypatch, llm)
    try:
        conversation_id = (
            await client.post(
                f"/api/v1/workspaces/{wid}/conversations", headers=headers, json={}
            )
        ).json()["id"]

        stopped = await client.post(
            f"/api/v1/workspaces/{wid}/conversations/{conversation_id}/stop",
            headers=headers,
        )
        assert stopped.status_code == 200
        assert stopped.json() == {"cancelled": False}

        renamed = await client.patch(
            f"/api/v1/workspaces/{wid}/conversations/{conversation_id}",
            headers=headers,
            json={"title": "Renamed"},
        )
        assert renamed.status_code == 200
        assert renamed.json()["title"] == "Renamed"

        await client.post(
            f"/api/v1/workspaces/{wid}/chat/complete",
            headers=headers,
            json={"query": "alpha", "conversation_id": conversation_id},
        )
        llm.answer = "Fresh answer [1]."
        regenerated = await client.post(
            f"/api/v1/workspaces/{wid}/conversations/{conversation_id}/regenerate",
            headers=headers,
        )
        assert regenerated.status_code == 200, regenerated.text
        assert regenerated.json()["answer"] == "Fresh answer [1]."
        messages = await client.get(
            f"/api/v1/workspaces/{wid}/conversations/{conversation_id}/messages",
            headers=headers,
        )
        assert [item["role"] for item in messages.json()] == ["user", "assistant"]
        assert messages.json()[-1]["content"] == "Fresh answer [1]."
    finally:
        app.dependency_overrides.pop(get_embedding_provider, None)


async def test_cancel_stream_helper() -> None:
    async def sleeper():
        await asyncio.sleep(30)

    task = asyncio.create_task(sleeper())
    conversation_id = uuid.uuid4()
    from services.chat import active_streams

    active_streams[conversation_id] = task
    assert cancel_stream(conversation_id) is True
    await asyncio.sleep(0)
    assert task.cancelled() is True
    assert cancel_stream(conversation_id) is False
    active_streams.pop(conversation_id, None)
