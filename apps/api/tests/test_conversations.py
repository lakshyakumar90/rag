"""Tests for conversations, rewriting, history truncation and auto-titles."""

import uuid

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

import services.chat as chat_module
import services.conversations as conversations_module
from api.v1.dependencies import get_embedding_provider
from core.config import get_settings
from main import app
from models import Document, DocumentChunk, DocumentStatus, User
from providers.llm.types import ChatMessage, Completion, Usage
from services.conversations import ConversationService

PASSWORD = "StrongPassw0rd!"
TERMS = ["alpha", "beta"]


class KeywordEmbeddings:
    dimension = len(TERMS)

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [await self.embed_query(text) for text in texts]

    async def embed_query(self, text: str) -> list[float]:
        vector = [0.0] * self.dimension
        for term in TERMS:
            if term in text.lower():
                vector[TERMS.index(term)] = 1.0
        return vector


class SmartFakeLLM:
    """Different answers for rewrite, title and grounded-answer calls."""

    def __init__(self) -> None:
        self.calls: list[list[ChatMessage]] = []

    async def complete(self, messages: list[ChatMessage], **opts):
        self.calls.append(list(messages))
        system = messages[0].content
        if system.startswith("Rewrite the user's final question"):
            return Completion("alpha standalone question", "stop", Usage(2, 1))
        if system.startswith("Write a short title"):
            return Completion("Alpha chat", "stop", Usage(2, 1))
        return Completion("Grounded answer [1].", "stop", Usage(10, 4))

    async def close(self):
        return None


class _Msg:
    def __init__(self, content: str) -> None:
        self.content = content


def test_history_truncation_keeps_newest_within_budget() -> None:
    messages = [_Msg("old " * 50), _Msg("middle " * 50), _Msg("newest")]
    kept = ConversationService.truncate_history(messages, budget=20)
    assert kept[-1].content == "newest"
    assert messages[0] not in kept
    assert all(m.content != messages[0].content for m in kept)


async def test_conversation_crud_and_isolation(client: AsyncClient) -> None:
    a_headers = await _login(client, "a@example.com")
    b_headers = await _login(client, "b@example.com")
    wid_a = await _workspace(client, a_headers, "workspace-a")
    wid_b = await _workspace(client, b_headers, "workspace-b")

    created = await client.post(
        f"/api/v1/workspaces/{wid_a}/conversations",
        headers=a_headers,
        json={"title": "My chat"},
    )
    assert created.status_code == 201
    conversation_id = created.json()["id"]
    assert created.json()["title"] == "My chat"

    listed = await client.get(
        f"/api/v1/workspaces/{wid_a}/conversations", headers=a_headers
    )
    assert [item["id"] for item in listed.json()] == [conversation_id]

    # Other users/workspaces cannot see or delete it.
    for response in (
        await client.get(
            f"/api/v1/workspaces/{wid_a}/conversations/{conversation_id}",
            headers=b_headers,
        ),
        await client.get(
            f"/api/v1/workspaces/{wid_b}/conversations/{conversation_id}",
            headers=a_headers,
        ),
        await client.delete(
            f"/api/v1/workspaces/{wid_a}/conversations/{conversation_id}",
            headers=b_headers,
        ),
    ):
        assert response.status_code == 403
        assert response.json()["error"]["code"] == "NOT_WORKSPACE_MEMBER"

    missing = await client.get(
        f"/api/v1/workspaces/{wid_a}/conversations/{uuid.uuid4()}",
        headers=a_headers,
    )
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "CONVERSATION_NOT_FOUND"

    deleted = await client.delete(
        f"/api/v1/workspaces/{wid_a}/conversations/{conversation_id}",
        headers=a_headers,
    )
    assert deleted.status_code == 204


async def test_chat_persists_messages_and_auto_title(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession], monkeypatch
) -> None:
    llm = SmartFakeLLM()
    monkeypatch.setattr(chat_module, "create_llm_provider", lambda name: llm)
    monkeypatch.setattr(conversations_module, "create_llm_provider", lambda name: llm)
    monkeypatch.setattr(get_settings(), "llm_provider", "fake")

    headers = await _login(client, "chat@example.com")
    wid = await _workspace(client, headers, "acme")
    await _seed(session_factory, wid)

    created = await client.post(
        f"/api/v1/workspaces/{wid}/conversations", headers=headers, json={}
    )
    conversation_id = created.json()["id"]
    assert created.json()["title"] == "New conversation"

    app.dependency_overrides[get_embedding_provider] = lambda: KeywordEmbeddings()
    try:
        response = await client.post(
            f"/api/v1/workspaces/{wid}/chat",
            headers=headers,
            json={"query": "alpha", "conversation_id": conversation_id},
        )
        assert response.status_code == 200, response.text
        assert response.json()["answer"] == "Grounded answer [1]."
        assert response.json()["conversation_id"] == conversation_id
        assert len(response.json()["citations"]) == 1

        messages = await client.get(
            f"/api/v1/workspaces/{wid}/conversations/{conversation_id}/messages",
            headers=headers,
        )
        assert messages.status_code == 200
        body = messages.json()
        assert [item["role"] for item in body] == ["user", "assistant"]
        assert body[0]["content"] == "alpha"
        assistant = body[1]
        assert assistant["content"] == "Grounded answer [1]."
        assert assistant["provider"] == "fake"
        assert assistant["model"] is None
        assert assistant["input_tokens"] == 10
        assert assistant["output_tokens"] == 4
        assert assistant["latency_ms"] >= 0
        assert (
            assistant["citations"][0]["chunk_id"]
            == response.json()["citations"][0]["chunk_id"]
        )

        conversation = await client.get(
            f"/api/v1/workspaces/{wid}/conversations/{conversation_id}",
            headers=headers,
        )
        assert conversation.json()["title"] == "Alpha chat"
    finally:
        app.dependency_overrides.pop(get_embedding_provider, None)


async def test_followup_rewrites_using_history(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession], monkeypatch
) -> None:
    llm = SmartFakeLLM()
    monkeypatch.setattr(chat_module, "create_llm_provider", lambda name: llm)
    monkeypatch.setattr(conversations_module, "create_llm_provider", lambda name: llm)
    monkeypatch.setattr(get_settings(), "llm_provider", "fake")

    headers = await _login(client, "follow@example.com")
    wid = await _workspace(client, headers, "follow")
    await _seed(session_factory, wid)
    conversation_id = (
        await client.post(
            f"/api/v1/workspaces/{wid}/conversations", headers=headers, json={}
        )
    ).json()["id"]

    app.dependency_overrides[get_embedding_provider] = lambda: KeywordEmbeddings()
    try:
        for query in ("alpha", "what about it?"):
            response = await client.post(
                f"/api/v1/workspaces/{wid}/chat",
                headers=headers,
                json={"query": query, "conversation_id": conversation_id},
            )
            assert response.status_code == 200, response.text

        messages = await client.get(
            f"/api/v1/workspaces/{wid}/conversations/{conversation_id}/messages",
            headers=headers,
        )
        user_contents = [
            item["content"] for item in messages.json() if item["role"] == "user"
        ]
        assert user_contents == ["alpha", "what about it?"]
        # The rewrite call saw the previous transcript.
        rewrite_calls = [
            call for call in llm.calls if call[0].content.startswith("Rewrite")
        ]
        assert len(rewrite_calls) == 1
        assert "user: alpha" in rewrite_calls[0][1].content
    finally:
        app.dependency_overrides.pop(get_embedding_provider, None)


async def _login(client: AsyncClient, email: str) -> dict[str, str]:
    await client.post(
        "/api/v1/auth/register", json={"email": email, "password": PASSWORD}
    )
    response = await client.post(
        "/api/v1/auth/login", json={"email": email, "password": PASSWORD}
    )
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


async def _workspace(client: AsyncClient, headers: dict[str, str], slug: str) -> str:
    response = await client.post(
        "/api/v1/workspaces", headers=headers, json={"name": slug, "slug": slug}
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


async def _seed(factory: async_sessionmaker[AsyncSession], wid: str) -> None:
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
