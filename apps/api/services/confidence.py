"""Multi-signal live answer confidence scoring."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from providers.llm.base import LLMProvider
from services.evals import evaluate_faithfulness

ConfidenceLevel = Literal["high", "medium", "low"]

_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")
_CITATION_RE = re.compile(r"\[(\d{1,3})\]")


@dataclass(frozen=True)
class ConfidenceResult:
    score: float
    level: ConfidenceLevel
    breakdown: dict


def _citation_coverage(answer: str, valid_numbers: set[int]) -> float:
    """Fraction of substantive sentences carrying at least one valid [n] citation."""
    sentences = [
        s.strip() for s in _SENTENCE_SPLIT.split(answer.strip()) if len(s.strip()) >= 8
    ]
    if not sentences:
        return 0.0
    cited = 0
    for sentence in sentences:
        nums = {int(m.group(1)) for m in _CITATION_RE.finditer(sentence)}
        if nums & valid_numbers:
            cited += 1
    return round(cited / len(sentences), 4)


def _level_for_score(score: float) -> ConfidenceLevel:
    if score >= 0.72:
        return "high"
    if score >= 0.42:
        return "medium"
    return "low"


async def compute_answer_confidence(
    *,
    answer: str,
    answerable: bool,
    search_items: list,
    valid_source_numbers: set[int],
    context_text: str = "",
    verify_faithfulness: bool = False,
    judge_llm: LLMProvider | None = None,
) -> ConfidenceResult:
    """Combine rerank/retrieval score, citation coverage, and faithfulness."""
    if not answerable or not answer.strip() or answer.strip().lower() == "i don't know":
        top_score = 0.0
        if search_items:
            top = search_items[0]
            raw = getattr(top, "rerank_score", None)
            top_score = float(raw if raw is not None else getattr(top, "score", 0.0))
        return ConfidenceResult(
            score=0.0,
            level="low",
            breakdown={
                "top_retrieval_score": round(max(0.0, min(1.0, top_score)), 4),
                "citation_coverage": 0.0,
                "faithfulness": None,
                "abstained": True,
            },
        )

    top_signal = 0.0
    reranked = False
    if search_items:
        top = search_items[0]
        if getattr(top, "rerank_score", None) is not None:
            top_signal = float(top.rerank_score)
            reranked = True
        else:
            top_signal = float(getattr(top, "score", 0.0))
    top_signal = round(max(0.0, min(1.0, top_signal)), 4)

    coverage = _citation_coverage(answer, valid_source_numbers)

    faithfulness_score: float | None = None
    if verify_faithfulness and context_text:
        faith_res = await evaluate_faithfulness(answer, context_text, judge_llm)
        faithfulness_score = faith_res.score

    if faithfulness_score is not None:
        combined = round(
            0.45 * top_signal + 0.25 * coverage + 0.30 * faithfulness_score, 4
        )
    else:
        combined = round(0.65 * top_signal + 0.35 * coverage, 4)

    combined = max(0.0, min(1.0, combined))
    return ConfidenceResult(
        score=combined,
        level=_level_for_score(combined),
        breakdown={
            "top_retrieval_score": top_signal,
            "reranked": reranked,
            "citation_coverage": coverage,
            "faithfulness": faithfulness_score,
            "abstained": False,
        },
    )
