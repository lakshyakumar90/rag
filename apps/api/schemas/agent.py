"""Typed tool inputs/outputs for the bounded agent loop."""

import uuid

from pydantic import BaseModel, ConfigDict, Field


class ToolInput(BaseModel):
    model_config = ConfigDict(extra="forbid")


class DocumentSearchInput(ToolInput):
    query: str = Field(min_length=1, max_length=500)
    top_k: int = Field(default=5, ge=1, le=10)
    document_ids: list[uuid.UUID] | None = None


class DocumentHit(BaseModel):
    chunk_id: uuid.UUID
    document_id: uuid.UUID
    filename: str
    text: str
    page_number: int | None
    heading_path: list[str] | None


class DocumentSearchOutput(BaseModel):
    source_type: str = "workspace"
    items: list[DocumentHit]


class WebSearchInput(ToolInput):
    query: str = Field(min_length=1, max_length=500)
    max_results: int = Field(default=3, ge=1, le=5)


class WebHit(BaseModel):
    title: str
    url: str
    snippet: str


class WebSearchOutput(BaseModel):
    source_type: str = "web"
    items: list[WebHit]
    unavailable_reason: str | None = None


class CalculatorInput(ToolInput):
    expression: str = Field(min_length=1, max_length=200)


class CalculatorOutput(BaseModel):
    expression: str
    value: float


class SummarizeInput(ToolInput):
    document_id: uuid.UUID


class SummarizeOutput(BaseModel):
    source_type: str = "workspace"
    document_id: uuid.UUID
    filename: str
    summary: str
    pages: list[int]


class ToolCall(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tool: str
    arguments: dict[str, object]


class AgentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=1, max_length=2000)
    provider: str | None = None
    model: str | None = Field(default=None, max_length=160)
    max_steps: int = Field(default=4, ge=1, le=8)
    deadline_seconds: float = Field(default=30.0, ge=1.0, le=120.0)
    conversation_id: uuid.UUID | None = None


class AgentToolEvent(BaseModel):
    type: str
    tool: str
    step: int
    detail: str = ""
    citations: list[dict] = Field(default_factory=list)
