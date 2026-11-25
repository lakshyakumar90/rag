"""Evaluation engine request/response schemas."""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class EvalDatasetCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=160)
    description: str | None = Field(default=None, max_length=2000)


class EvalDatasetResponse(BaseModel):
    id: uuid.UUID
    workspace_id: uuid.UUID
    name: str
    description: str | None
    case_count: int = 0
    created_at: datetime


class EvalCaseCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: str = Field(min_length=1, max_length=4000)
    expected_answer: str | None = None
    expected_document_ids: list[str] | None = None
    expected_chunk_ids: list[str] | None = None
    expected_keywords: list[str] | None = None
    source_message_id: uuid.UUID | None = None


class EvalCaseResponse(BaseModel):
    id: uuid.UUID
    dataset_id: uuid.UUID
    workspace_id: uuid.UUID
    question: str
    expected_answer: str | None
    expected_document_ids: list[str] | None
    expected_chunk_ids: list[str] | None
    expected_keywords: list[str] | None
    source_message_id: uuid.UUID | None
    created_at: datetime


class EvalRunCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    top_k: int = Field(default=5, ge=1, le=50)
    run_async: bool = False


class EvalResultResponse(BaseModel):
    id: uuid.UUID
    run_id: uuid.UUID
    case_id: uuid.UUID
    question: str
    generated_answer: str | None
    retrieved_document_ids: list[str] | None
    retrieved_chunk_ids: list[str] | None
    recall_at_k: float | None
    mrr: float | None
    ndcg_at_k: float | None
    faithfulness: float | None
    answer_relevancy: float | None
    citation_accuracy: float | None
    judge_reasoning: dict | None
    passed: bool
    latency_ms: float | None


class EvalRunResponse(BaseModel):
    id: uuid.UUID
    dataset_id: uuid.UUID
    workspace_id: uuid.UUID
    status: str
    top_k: int
    total_cases: int
    completed_cases: int
    recall_at_k: float | None
    mrr: float | None
    ndcg_at_k: float | None
    faithfulness: float | None
    answer_relevancy: float | None
    citation_accuracy: float | None
    error: str | None
    created_at: datetime
    completed_at: datetime | None


class EvalRunDetailResponse(EvalRunResponse):
    results: list[EvalResultResponse] = Field(default_factory=list)
    failures: list[EvalResultResponse] = Field(default_factory=list)
