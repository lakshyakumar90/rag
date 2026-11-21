"""Production-feature request/response schemas."""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class FeedbackRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    vote: str = Field(pattern="^(up|down)$")
    comment: str | None = Field(default=None, max_length=1000)


class FeedbackResponse(BaseModel):
    message_id: uuid.UUID
    vote: str
    comment: str | None
    created_at: datetime


class UsageResponse(BaseModel):
    workspace_id: uuid.UUID
    queries: int
    answers: int
    input_tokens: int
    output_tokens: int
    estimated_token_answers: int
    documents: int
    storage_bytes: int
    feedback_up: int
    feedback_down: int


class QuestionStat(BaseModel):
    question: str
    count: int


class DocumentStat(BaseModel):
    document_id: uuid.UUID | None
    filename: str
    citations: int


class AnalyticsResponse(BaseModel):
    workspace_id: uuid.UUID
    most_asked: list[QuestionStat]
    low_confidence_count: int
    low_confidence_questions: list[QuestionStat]
    most_cited: list[DocumentStat]


class AuditEntryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    workspace_id: uuid.UUID | None
    actor_email: str
    action: str
    target_type: str | None
    target_id: str | None
    details: dict | None
    created_at: datetime
