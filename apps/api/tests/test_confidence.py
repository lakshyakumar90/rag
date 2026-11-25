"""Tests for Prompt 2.2: Live Answer Confidence Score & Feedback-to-Eval Promotion."""

import uuid
from types import SimpleNamespace

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from api.v1.dependencies import get_embedding_provider
from main import app
from models import Conversation, Document, DocumentChunk, DocumentStatus, Message, User
from services.confidence import compute_answer_confidence

PASSWORD = "StrongPassw0rd!"


class _FakeEmbeddings:
    dimension = 4

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [await self.embed_query(t) for t in texts]

    async def embed_query(self, text: str) -> list[float]:
        return [1.0, 0.0, 0.0, 0.0] if "alpha" in text.lower() else [0.0, 0.0, 0.0, 0.0]


async def test_confidence_high_vs_low_abstention() -> None:
    high = await compute_answer_confidence(
        answer="Alpha supports SSO [1]. It enforces MFA for all admins [1].",
        answerable=True,
        search_items=[SimpleNamespace(rerank_score=0.91, score=0.91)],
        valid_source_numbers={1},
    )
    assert high.level == "high"
    assert high.score >= 0.72
    assert high.breakdown["citation_coverage"] == pytest.approx(1.0)
    assert high.breakdown["reranked"] is True

    low = await compute_answer_confidence(
        answer="I don't know",
        answerable=False,
        search_items=[SimpleNamespace(rerank_score=0.11, score=0.11)],
        valid_source_numbers=set(),
    )
    assert low.level == "low"
    assert low.score == 0.0
    assert low.breakdown["abstained"] is True


async def test_promote_message_to_eval_endpoint(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    app.dependency_overrides[get_embedding_provider] = lambda: _FakeEmbeddings()
    try:
        await client.post(
            "/api/v1/auth/register",
            json={"email": "conf@example.com", "password": PASSWORD},
        )
        login = await client.post(
            "/api/v1/auth/login",
            json={"email": "conf@example.com", "password": PASSWORD},
        )
        headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
        wid = (
            await client.post(
                "/api/v1/workspaces",
                headers=headers,
                json={"name": "Conf WS", "slug": "conf-ws"},
            )
        ).json()["id"]

        async with session_factory() as session:
            owner = (await session.execute(select(User))).scalar_one()
            doc = Document(
                workspace_id=uuid.UUID(wid),
                uploaded_by=owner.id,
                filename="alpha.txt",
                mime_type="text/plain",
                size=40,
                sha256="c" * 64,
                storage_key=f"{wid}/alpha.txt",
                status=DocumentStatus.READY,
                embedding_model="test",
                embedding_dim=4,
            )
            session.add(doc)
            await session.flush()
            session.add(
                DocumentChunk(
                    document_id=doc.id,
                    workspace_id=uuid.UUID(wid),
                    chunk_index=0,
                    content="Alpha policy requires MFA.",
                    embedding=[1.0, 0.0, 0.0, 0.0],
                    search_vector="alpha policy requires mfa",
                )
            )
            conv = Conversation(
                workspace_id=uuid.UUID(wid),
                user_id=owner.id,
                title="Confidence check",
            )
            session.add(conv)
            await session.flush()
            user_msg = Message(
                conversation_id=conv.id,
                sequence=1,
                role="user",
                content="Does alpha require MFA?",
            )
            asst_msg = Message(
                conversation_id=conv.id,
                sequence=2,
                role="assistant",
                content="I don't know",
                answerable=False,
                confidence_score=0.0,
                confidence_level="low",
                confidence_breakdown={"abstained": True},
            )
            session.add_all([user_msg, asst_msg])
            await session.commit()
            msg_id = str(asst_msg.id)

        promoted = await client.post(
            f"/api/v1/workspaces/{wid}/messages/{msg_id}/promote-to-eval",
            headers=headers,
            json={"expected_answer": "Yes, Alpha requires MFA."},
        )
        assert promoted.status_code == 201, promoted.text
        case = promoted.json()
        assert case["question"] == "Does alpha require MFA?"
        assert case["expected_answer"] == "Yes, Alpha requires MFA."
        assert case["source_message_id"] == msg_id

        # Out-of-corpus chat streams low confidence SSE event cleanly
        import json

        out_of_corpus = await client.post(
            f"/api/v1/workspaces/{wid}/chat",
            headers=headers,
            json={"query": "unrelated quantum gravity"},
        )
        assert out_of_corpus.status_code == 200
        events = [
            json.loads(line.removeprefix("data: "))
            for line in out_of_corpus.text.splitlines()
            if line.startswith("data: ")
        ]
        conf_events = [e for e in events if e["type"] == "confidence"]
        done_events = [e for e in events if e["type"] == "done"]
        assert len(conf_events) == 1
        assert conf_events[0]["confidence_level"] == "low"
        assert conf_events[0]["confidence_score"] == 0.0
        assert done_events[0]["answerable"] is False
    finally:
        app.dependency_overrides.pop(get_embedding_provider, None)
