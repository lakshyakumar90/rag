"""Tests for Prompt 2.1: From-scratch RAG evaluation engine and REST API."""

import json
import uuid
from types import SimpleNamespace

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from api.v1.dependencies import get_embedding_provider
from main import app
from models import Document, DocumentChunk, DocumentStatus, User
from services.evals import (
    compute_mrr,
    compute_ndcg_at_k,
    compute_recall_at_k,
    evaluate_answer_relevancy,
    evaluate_citation_accuracy,
    evaluate_faithfulness,
)

PASSWORD = "StrongPassw0rd!"


class _FakeJudgeLLM:
    def __init__(self, payload: dict) -> None:
        self._payload = payload

    async def complete(self, messages, **opts):
        return SimpleNamespace(text=json.dumps(self._payload))


class _OneHotEmbeddings:
    dimension = 4

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [await self.embed_query(t) for t in texts]

    async def embed_query(self, text: str) -> list[float]:
        low = text.lower()
        return [
            1.0 if "vacation" in low or "pto" in low else 0.0,
            1.0 if "expense" in low or "receipt" in low else 0.0,
            1.0 if "security" in low or "mfa" in low else 0.0,
            0.1,
        ]


def test_retrieval_metrics_recall_mrr_ndcg() -> None:
    retrieved = ["d1", "d2", "d3", "d4", "d5"]
    expected = ["d2", "d4"]

    assert compute_recall_at_k(retrieved, expected, k=2) == pytest.approx(0.5)
    assert compute_recall_at_k(retrieved, expected, k=5) == pytest.approx(1.0)
    assert compute_mrr(retrieved, expected) == pytest.approx(0.5)  # first hit at rank 2
    assert compute_mrr(["d9", "d8"], expected) == 0.0

    ndcg_perfect = compute_ndcg_at_k(["d2", "d4", "d1"], expected, k=3)
    ndcg_lower = compute_ndcg_at_k(["d1", "d2", "d4"], expected, k=3)
    assert ndcg_perfect == pytest.approx(1.0)
    assert 0.0 < ndcg_lower < 1.0


async def test_llm_as_a_judge_strict_json_parsing() -> None:
    faith_judge = _FakeJudgeLLM(
        {
            "claims": [
                {
                    "claim": "PTO is 20 days.",
                    "verdict": "SUPPORTED",
                    "reason": "In doc",
                },
                {
                    "claim": "PTO rolls over 10 days.",
                    "verdict": "UNSUPPORTED",
                    "reason": "Not stated",
                },
            ],
            "reasoning": "1 of 2 claims supported.",
        }
    )
    faith = await evaluate_faithfulness(
        "PTO is 20 days. PTO rolls over 10 days.",
        "Employees receive 20 days of PTO per year.",
        judge_llm=faith_judge,  # type: ignore[arg-type]
    )
    assert faith.score == pytest.approx(0.5)
    assert faith.details["supported"] == 1

    relev_judge = _FakeJudgeLLM(
        {"score": 0.92, "reasoning": "Directly answers PTO question."}
    )
    relev = await evaluate_answer_relevancy(
        "How many PTO days do employees get?",
        "Employees get 20 PTO days [1].",
        judge_llm=relev_judge,  # type: ignore[arg-type]
    )
    assert relev.score == pytest.approx(0.92)

    cite_judge = _FakeJudgeLLM(
        {
            "checks": [{"citation": 1, "valid": True, "reason": "Matches source 1"}],
            "score": 1.0,
            "reasoning": "All citations verified.",
        }
    )
    cite = await evaluate_citation_accuracy(
        "Employees get 20 PTO days [1].",
        {1: "Employees receive 20 days of PTO per year."},
        judge_llm=cite_judge,  # type: ignore[arg-type]
    )
    assert cite.score == pytest.approx(1.0)


async def test_eval_rest_endpoints_end_to_end(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    app.dependency_overrides[get_embedding_provider] = lambda: _OneHotEmbeddings()
    try:
        await client.post(
            "/api/v1/auth/register",
            json={"email": "eval@example.com", "password": PASSWORD},
        )
        login = await client.post(
            "/api/v1/auth/login",
            json={"email": "eval@example.com", "password": PASSWORD},
        )
        headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
        wid = (
            await client.post(
                "/api/v1/workspaces",
                headers=headers,
                json={"name": "Eval WS", "slug": "eval-ws"},
            )
        ).json()["id"]

        async with session_factory() as session:
            owner_id = (await session.execute(select(User))).scalar_one().id
            doc = Document(
                workspace_id=uuid.UUID(wid),
                uploaded_by=owner_id,
                filename="benefits.txt",
                mime_type="text/plain",
                size=100,
                sha256="b" * 64,
                storage_key=f"{wid}/benefits.txt",
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
                    content="Full-time employees receive 20 days of paid vacation PTO.",
                    embedding=[1.0, 0.0, 0.0, 0.1],
                    search_vector="employees receive 20 days of paid vacation pto",
                )
            )
            await session.commit()
            doc_id = str(doc.id)

        ds = await client.post(
            f"/api/v1/workspaces/{wid}/evals/datasets",
            headers=headers,
            json={"name": "HR Golden Set", "description": "Core HR policies"},
        )
        assert ds.status_code == 201, ds.text
        dataset_id = ds.json()["id"]

        case = await client.post(
            f"/api/v1/workspaces/{wid}/evals/datasets/{dataset_id}/cases",
            headers=headers,
            json={
                "question": "How many vacation PTO days do employees get?",
                "expected_document_ids": [doc_id],
            },
        )
        assert case.status_code == 201, case.text

        run_resp = await client.post(
            f"/api/v1/workspaces/{wid}/evals/datasets/{dataset_id}/runs",
            headers=headers,
            json={"top_k": 5, "run_async": False},
        )
        assert run_resp.status_code == 201, run_resp.text
        run = run_resp.json()
        assert run["status"] == "completed"
        assert run["recall_at_k"] == pytest.approx(1.0)
        assert run["mrr"] == pytest.approx(1.0)
        assert run["faithfulness"] is not None

        detail = await client.get(
            f"/api/v1/workspaces/{wid}/evals/runs/{run['id']}",
            headers=headers,
        )
        assert detail.status_code == 200
        assert len(detail.json()["results"]) == 1
    finally:
        app.dependency_overrides.pop(get_embedding_provider, None)
