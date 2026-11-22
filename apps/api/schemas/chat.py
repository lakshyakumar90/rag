"""Grounded chat request/response schemas."""

import uuid

from pydantic import BaseModel, ConfigDict, Field


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=1, max_length=2000)
    top_k: int | None = Field(default=None, ge=1, le=50)
    document_ids: list[uuid.UUID] | None = None
    model: str | None = Field(default=None, max_length=160, pattern=r"^[\w./:+#-]+$")
    provider: str | None = Field(default=None, max_length=50)
    conversation_id: uuid.UUID | None = None


class SourceRef(BaseModel):
    number: int
    chunk_id: uuid.UUID
    document_id: uuid.UUID
    filename: str
    page_number: int | None
    heading_path: list[str] | None
    # "workspace" citations point at a chunk; "web" citations carry a URL.
    source_type: str = "workspace"
    url: str | None = None


class Citation(SourceRef):
    """A source referenced by the model as [n] in the answer."""


class ChatResponse(BaseModel):
    answer: str
    answerable: bool
    provider: str
    # The model that actually generated this answer (resolved default or override).
    model: str | None = None
    citations: list[Citation]
    sources: list[SourceRef]
    conversation_id: uuid.UUID | None = None
