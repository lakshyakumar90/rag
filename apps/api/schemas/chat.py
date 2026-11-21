"""Grounded chat request/response schemas."""

import uuid

from pydantic import BaseModel, ConfigDict, Field


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=1, max_length=2000)
    top_k: int | None = Field(default=None, ge=1, le=50)
    document_ids: list[uuid.UUID] | None = None
    provider: str | None = Field(default=None, max_length=50)


class SourceRef(BaseModel):
    number: int
    chunk_id: uuid.UUID
    document_id: uuid.UUID
    filename: str
    page_number: int | None
    heading_path: list[str] | None


class Citation(SourceRef):
    """A source referenced by the model as [n] in the answer."""


class ChatResponse(BaseModel):
    answer: str
    answerable: bool
    provider: str
    citations: list[Citation]
    sources: list[SourceRef]
