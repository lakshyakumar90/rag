"""From-scratch RAG eval engine: retrieval metrics + LLM-as-a-Judge."""

from __future__ import annotations

import json
import logging
import math
import re
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.prompting import SYSTEM_PROMPT, build_context
from models.evals import EvalCase, EvalDataset, EvalResult, EvalRun
from providers.embeddings import EmbeddingProvider
from providers.llm.base import LLMProvider
from providers.llm.types import ChatMessage
from providers.rerank import Reranker
from services.qdrant_index import QdrantIndexService
from services.retrieval import RetrievalService
from services.workspaces import WorkspaceContext

logger = logging.getLogger(__name__)

_CITATION_RE = re.compile(r"\[(\d{1,3})\]")
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")


# ---------------------------------------------------------------------------
# Pure-Python Retrieval Metrics
# ---------------------------------------------------------------------------


def compute_recall_at_k(
    retrieved_ids: list[str], expected_ids: list[str], k: int
) -> float:
    """Fraction of expected IDs recovered within the top-k retrieved IDs."""
    if not expected_ids:
        return 1.0
    if k <= 0 or not retrieved_ids:
        return 0.0
    expected = set(expected_ids)
    top_k = set(retrieved_ids[:k])
    return round(len(expected & top_k) / len(expected), 4)


def compute_mrr(retrieved_ids: list[str], expected_ids: list[str]) -> float:
    """Mean Reciprocal Rank (1/rank of the first relevant hit, or 0.0)."""
    if not expected_ids:
        return 1.0
    expected = set(expected_ids)
    for rank, item in enumerate(retrieved_ids, start=1):
        if item in expected:
            return round(1.0 / rank, 4)
    return 0.0


def compute_ndcg_at_k(
    retrieved_ids: list[str], expected_ids: list[str], k: int
) -> float:
    """Normalized Discounted Cumulative Gain @ K (binary relevance)."""
    if not expected_ids:
        return 1.0
    if k <= 0 or not retrieved_ids:
        return 0.0
    expected = set(expected_ids)
    dcg = 0.0
    seen: set[str] = set()
    for rank, item in enumerate(retrieved_ids[:k], start=1):
        if item in expected and item not in seen:
            seen.add(item)
            dcg += 1.0 / math.log2(rank + 1)
    ideal_hits = min(len(expected), k)
    idcg = sum(1.0 / math.log2(rank + 1) for rank in range(1, ideal_hits + 1))
    if idcg == 0.0:
        return 0.0
    return round(dcg / idcg, 4)


# ---------------------------------------------------------------------------
# From-Scratch LLM-as-a-Judge Metrics (Strict JSON with deterministic fallback)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class JudgeMetricResult:
    score: float
    reasoning: str
    details: dict


def _extract_json_object(raw: str) -> dict:
    """Parse strict JSON from an LLM judge response (tolerates ```json fences)."""
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start >= 0 and end > start:
        cleaned = cleaned[start : end + 1]
    data = json.loads(cleaned)
    if not isinstance(data, dict):
        raise ValueError("Judge output must be a JSON object")
    return data


def _clamp01(value: float) -> float:
    return round(max(0.0, min(1.0, float(value))), 4)


def _token_overlap(left: str, right: str) -> float:
    left_tokens = {tok for tok in re.findall(r"[a-zA-Z0-9_]{3,}", left.lower())}
    right_tokens = {tok for tok in re.findall(r"[a-zA-Z0-9_]{3,}", right.lower())}
    if not left_tokens:
        return 1.0
    return len(left_tokens & right_tokens) / len(left_tokens)


async def evaluate_faithfulness(
    answer: str, context: str, judge_llm: LLMProvider | None = None
) -> JudgeMetricResult:
    """Extract atomic claims from answer and check SUPPORTED vs UNSUPPORTED."""
    if not answer.strip() or answer.strip().lower() == "i don't know":
        return JudgeMetricResult(
            score=1.0,
            reasoning="Abstention or empty answer makes no unsupported claims.",
            details={"claims": []},
        )

    if judge_llm is not None:
        prompt = (
            "You are a strict RAG faithfulness judge.\n"
            "1. Decompose the ANSWER into atomic factual claims.\n"
            "2. For each claim, classify it as SUPPORTED or UNSUPPORTED based ONLY "
            "on CONTEXT.\n"
            "Return STRICT JSON ONLY with keys: "
            '{"claims": [{"claim": "...", "verdict": "SUPPORTED"|"UNSUPPORTED", '
            '"reason": "..."}], "reasoning": "..."}.\n\n'
            f"<context>\n{context[:4000]}\n</context>\n\n"
            f"<answer>\n{answer[:2000]}\n</answer>"
        )
        try:
            resp = await judge_llm.complete(
                [ChatMessage(role="user", content=prompt)],
                max_tokens=512,
                temperature=0.0,
            )
            data = _extract_json_object(resp.text)
            claims = data.get("claims") or []
            if claims:
                supported = sum(
                    1
                    for c in claims
                    if str(c.get("verdict", "")).upper() == "SUPPORTED"
                )
                score = _clamp01(supported / len(claims))
                return JudgeMetricResult(
                    score=score,
                    reasoning=str(data.get("reasoning") or ""),
                    details={
                        "claims": claims,
                        "supported": supported,
                        "total": len(claims),
                    },
                )
        except Exception as exc:
            logger.warning("Faithfulness judge LLM fallback: %s", exc)

    # Deterministic lexical claim-support fallback
    sentences = [
        s.strip() for s in _SENTENCE_SPLIT_RE.split(answer.strip()) if s.strip()
    ]
    claims = []
    supported = 0
    for sentence in sentences:
        overlap = _token_overlap(sentence, context)
        verdict = "SUPPORTED" if overlap >= 0.35 else "UNSUPPORTED"
        if verdict == "SUPPORTED":
            supported += 1
        claims.append(
            {"claim": sentence, "verdict": verdict, "overlap": round(overlap, 3)}
        )
    score = _clamp01(supported / max(1, len(claims)))
    return JudgeMetricResult(
        score=score,
        reasoning="Lexical claim support ratio against retrieved context.",
        details={"claims": claims, "supported": supported, "total": len(claims)},
    )


async def evaluate_answer_relevancy(
    query: str, answer: str, judge_llm: LLMProvider | None = None
) -> JudgeMetricResult:
    """Score 0.0-1.0 on whether the answer directly addresses the query."""
    if not answer.strip():
        return JudgeMetricResult(score=0.0, reasoning="Empty answer.", details={})

    if judge_llm is not None:
        prompt = (
            "You are a strict RAG answer relevancy judge.\n"
            "Score from 0.0 to 1.0 whether ANSWER directly and completely addresses "
            "QUERY.\n"
            'Return STRICT JSON ONLY: {"score": 0.0, "reasoning": "..."}.\n\n'
            f"QUERY: {query}\n\nANSWER: {answer[:2000]}"
        )
        try:
            resp = await judge_llm.complete(
                [ChatMessage(role="user", content=prompt)],
                max_tokens=256,
                temperature=0.0,
            )
            data = _extract_json_object(resp.text)
            return JudgeMetricResult(
                score=_clamp01(float(data["score"])),
                reasoning=str(data.get("reasoning") or ""),
                details=data,
            )
        except Exception as exc:
            logger.warning("Relevancy judge LLM fallback: %s", exc)

    overlap = _token_overlap(query, answer)
    return JudgeMetricResult(
        score=_clamp01(0.4 + 0.6 * overlap if overlap > 0 else 0.1),
        reasoning="Lexical query-to-answer relevancy heuristic.",
        details={"token_overlap": round(overlap, 3)},
    )


async def evaluate_citation_accuracy(
    answer: str,
    sources: dict[int, str],
    judge_llm: LLMProvider | None = None,
) -> JudgeMetricResult:
    """Verify every [n] marker maps to a valid chunk supporting the citing sentence."""
    sentences = [
        s.strip() for s in _SENTENCE_SPLIT_RE.split(answer.strip()) if s.strip()
    ]
    cited_pairs: list[tuple[str, int]] = []
    for sentence in sentences:
        for match in _CITATION_RE.finditer(sentence):
            cited_pairs.append((sentence, int(match.group(1))))

    if not cited_pairs:
        # No citations emitted: 1.0 only if abstention, otherwise 0.0.
        if answer.strip().lower() == "i don't know":
            return JudgeMetricResult(
                score=1.0,
                reasoning="Abstention requires no citations.",
                details={"checks": []},
            )
        return JudgeMetricResult(
            score=0.0,
            reasoning="Substantive answer contains no [n] citations.",
            details={"checks": []},
        )

    if judge_llm is not None:
        source_block = "\n".join(
            f"[{num}]: {text[:500]}" for num, text in sorted(sources.items())
        )
        prompt = (
            "You are a strict citation verification judge.\n"
            "For each [n] citation in ANSWER, verify whether source [n] exists and "
            "actually supports the sentence citing it.\n"
            'Return STRICT JSON ONLY: {"checks": [{"citation": 1, "valid": true, '
            '"reason": "..."}], "score": 0.0, "reasoning": "..."}.\n\n'
            f"SOURCES:\n{source_block}\n\nANSWER:\n{answer[:2000]}"
        )
        try:
            resp = await judge_llm.complete(
                [ChatMessage(role="user", content=prompt)],
                max_tokens=512,
                temperature=0.0,
            )
            data = _extract_json_object(resp.text)
            checks = data.get("checks") or []
            if "score" in data:
                score = _clamp01(float(data["score"]))
            elif checks:
                valid_count = sum(1 for c in checks if bool(c.get("valid")))
                score = _clamp01(valid_count / len(checks))
            else:
                score = 0.0
            return JudgeMetricResult(
                score=score,
                reasoning=str(data.get("reasoning") or ""),
                details={"checks": checks},
            )
        except Exception as exc:
            logger.warning("Citation accuracy judge LLM fallback: %s", exc)

    checks = []
    valid = 0
    for sentence, num in cited_pairs:
        source_text = sources.get(num)
        if source_text is None:
            checks.append(
                {"citation": num, "valid": False, "reason": "Missing source id"}
            )
            continue
        overlap = _token_overlap(sentence, source_text)
        is_valid = overlap >= 0.2
        if is_valid:
            valid += 1
        checks.append(
            {
                "citation": num,
                "valid": is_valid,
                "overlap": round(overlap, 3),
            }
        )
    return JudgeMetricResult(
        score=_clamp01(valid / len(cited_pairs)),
        reasoning="Verified [n] markers against mapped source chunks.",
        details={"checks": checks, "valid": valid, "total": len(cited_pairs)},
    )


# ---------------------------------------------------------------------------
# Eval Service (DB persistence + Suite Execution)
# ---------------------------------------------------------------------------


class EvalService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create_dataset(
        self,
        workspace_id: uuid.UUID,
        user_id: uuid.UUID | None,
        name: str,
        description: str | None = None,
    ) -> EvalDataset:
        dataset = EvalDataset(
            workspace_id=workspace_id,
            created_by=user_id,
            name=name.strip(),
            description=description,
        )
        self._session.add(dataset)
        await self._session.commit()
        await self._session.refresh(dataset)
        return dataset

    async def list_datasets(
        self, workspace_id: uuid.UUID
    ) -> list[tuple[EvalDataset, int]]:
        stmt = (
            select(EvalDataset, func.count(EvalCase.id))
            .outerjoin(EvalCase, EvalCase.dataset_id == EvalDataset.id)
            .where(EvalDataset.workspace_id == workspace_id)
            .group_by(EvalDataset.id)
            .order_by(EvalDataset.created_at.desc())
        )
        rows = (await self._session.execute(stmt)).all()
        return [(row[0], int(row[1])) for row in rows]

    async def add_case(
        self,
        workspace_id: uuid.UUID,
        dataset_id: uuid.UUID,
        question: str,
        expected_answer: str | None = None,
        expected_document_ids: list[str] | None = None,
        expected_chunk_ids: list[str] | None = None,
        expected_keywords: list[str] | None = None,
        source_message_id: uuid.UUID | None = None,
    ) -> EvalCase:
        case = EvalCase(
            dataset_id=dataset_id,
            workspace_id=workspace_id,
            question=question.strip(),
            expected_answer=expected_answer,
            expected_document_ids=expected_document_ids,
            expected_chunk_ids=expected_chunk_ids,
            expected_keywords=expected_keywords,
            source_message_id=source_message_id,
        )
        self._session.add(case)
        await self._session.commit()
        await self._session.refresh(case)
        return case

    async def list_cases(
        self, workspace_id: uuid.UUID, dataset_id: uuid.UUID
    ) -> list[EvalCase]:
        stmt = (
            select(EvalCase)
            .where(
                EvalCase.workspace_id == workspace_id,
                EvalCase.dataset_id == dataset_id,
            )
            .order_by(EvalCase.created_at.asc())
        )
        return list((await self._session.execute(stmt)).scalars().all())

    async def create_run(
        self, workspace_id: uuid.UUID, dataset_id: uuid.UUID, top_k: int = 5
    ) -> EvalRun:
        cases = await self.list_cases(workspace_id, dataset_id)
        run = EvalRun(
            dataset_id=dataset_id,
            workspace_id=workspace_id,
            status="pending",
            top_k=top_k,
            total_cases=len(cases),
            completed_cases=0,
        )
        self._session.add(run)
        await self._session.commit()
        await self._session.refresh(run)
        return run

    async def execute_run(
        self,
        run_id: uuid.UUID,
        context: WorkspaceContext,
        embeddings: EmbeddingProvider,
        llm: LLMProvider | None = None,
        judge_llm: LLMProvider | None = None,
        reranker: Reranker | None = None,
        indexer: QdrantIndexService | None = None,
    ) -> EvalRun:
        run = await self._session.get(EvalRun, run_id)
        if run is None:
            raise ValueError(f"EvalRun {run_id} not found")

        run.status = "running"
        await self._session.commit()

        retrieval = RetrievalService(self._session, embeddings, reranker, indexer)
        cases = await self.list_cases(run.workspace_id, run.dataset_id)
        run.total_cases = len(cases)

        recalls: list[float] = []
        mrrs: list[float] = []
        ndcgs: list[float] = []
        faiths: list[float] = []
        relevs: list[float] = []
        cites: list[float] = []

        try:
            for case in cases:
                t0 = time.perf_counter()
                search_res = await retrieval.search(
                    context, case.question, top_k=run.top_k
                )
                retrieved_doc_ids = [str(item.document_id) for item in search_res.items]
                retrieved_chunk_ids = [str(item.chunk_id) for item in search_res.items]

                if case.expected_chunk_ids:
                    recall = compute_recall_at_k(
                        retrieved_chunk_ids, case.expected_chunk_ids, run.top_k
                    )
                    mrr = compute_mrr(retrieved_chunk_ids, case.expected_chunk_ids)
                    ndcg = compute_ndcg_at_k(
                        retrieved_chunk_ids, case.expected_chunk_ids, run.top_k
                    )
                else:
                    expected_docs = case.expected_document_ids or []
                    recall = compute_recall_at_k(
                        retrieved_doc_ids, expected_docs, run.top_k
                    )
                    mrr = compute_mrr(retrieved_doc_ids, expected_docs)
                    ndcg = compute_ndcg_at_k(
                        retrieved_doc_ids, expected_docs, run.top_k
                    )

                built = build_context(search_res.items, token_budget=2000)
                source_map = {src.number: src.text for src in built.sources}

                if not search_res.answerable:
                    answer = "I don't know"
                elif llm is not None:
                    resp = await llm.complete(
                        [
                            ChatMessage(role="system", content=SYSTEM_PROMPT),
                            ChatMessage(
                                role="user",
                                content=f"{built.text}\n\nQ: {case.question}",
                            ),
                        ],
                        max_tokens=384,
                        temperature=0.0,
                    )
                    answer = resp.text.strip()
                else:
                    # Extractive fallback when running offline without an LLM
                    answer = (
                        f"{built.sources[0].text[:300]} [1]"
                        if built.sources
                        else "I don't know"
                    )

                faith = await evaluate_faithfulness(answer, built.text, judge_llm)
                relev = await evaluate_answer_relevancy(
                    case.question, answer, judge_llm
                )
                cite = await evaluate_citation_accuracy(answer, source_map, judge_llm)
                elapsed_ms = round((time.perf_counter() - t0) * 1000.0, 2)

                passed = recall >= 0.5 and faith.score >= 0.7 and cite.score >= 0.7
                row = EvalResult(
                    run_id=run.id,
                    case_id=case.id,
                    workspace_id=run.workspace_id,
                    question=case.question,
                    generated_answer=answer,
                    retrieved_document_ids=retrieved_doc_ids,
                    retrieved_chunk_ids=retrieved_chunk_ids,
                    recall_at_k=recall,
                    mrr=mrr,
                    ndcg_at_k=ndcg,
                    faithfulness=faith.score,
                    answer_relevancy=relev.score,
                    citation_accuracy=cite.score,
                    judge_reasoning={
                        "faithfulness": faith.reasoning,
                        "answer_relevancy": relev.reasoning,
                        "citation_accuracy": cite.reasoning,
                    },
                    passed=passed,
                    latency_ms=elapsed_ms,
                )
                self._session.add(row)
                recalls.append(recall)
                mrrs.append(mrr)
                ndcgs.append(ndcg)
                faiths.append(faith.score)
                relevs.append(relev.score)
                cites.append(cite.score)
                run.completed_cases += 1

            def _avg(vals: list[float]) -> float | None:
                return round(sum(vals) / len(vals), 4) if vals else None

            run.recall_at_k = _avg(recalls)
            run.mrr = _avg(mrrs)
            run.ndcg_at_k = _avg(ndcgs)
            run.faithfulness = _avg(faiths)
            run.answer_relevancy = _avg(relevs)
            run.citation_accuracy = _avg(cites)
            run.status = "completed"
            run.completed_at = datetime.now(UTC)
            await self._session.commit()
            await self._session.refresh(run)
            return run
        except Exception as exc:
            run.status = "failed"
            run.error = f"{type(exc).__name__}: {exc}"[:2000]
            await self._session.commit()
            raise

    async def list_runs(self, workspace_id: uuid.UUID) -> list[EvalRun]:
        stmt = (
            select(EvalRun)
            .where(EvalRun.workspace_id == workspace_id)
            .order_by(EvalRun.created_at.desc())
        )
        return list((await self._session.execute(stmt)).scalars().all())

    async def get_run_with_results(
        self, workspace_id: uuid.UUID, run_id: uuid.UUID
    ) -> tuple[EvalRun | None, list[EvalResult]]:
        run = (
            await self._session.execute(
                select(EvalRun).where(
                    EvalRun.id == run_id, EvalRun.workspace_id == workspace_id
                )
            )
        ).scalar_one_or_none()
        if run is None:
            return None, []
        results = list(
            (
                await self._session.execute(
                    select(EvalResult)
                    .where(EvalResult.run_id == run.id)
                    .order_by(EvalResult.created_at.asc())
                )
            )
            .scalars()
            .all()
        )
        return run, results
