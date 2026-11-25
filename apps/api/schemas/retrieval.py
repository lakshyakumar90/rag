"""Retrieval request/response schemas."""

import uuid

from pydantic import BaseModel, ConfigDict, Field


class SearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=1, max_length=2000)
    top_k: int | None = Field(default=None, ge=1, le=50)
    document_ids: list[uuid.UUID] | None = None


class SearchResult(BaseModel):
    chunk_id: uuid.UUID
    document_id: uuid.UUID
    filename: str
    text: str
    score: float
    page_number: int | None
    heading_path: list[str] | None
    dense_rank: int | None = None
    lexical_rank: int | None = None
    rrf_score: float | None = None
    rerank_score: float | None = None
    retrieval_ms: float | None = None
    parent_content: str | None = None
    context_header: str | None = None
    char_start: int | None = None
    char_end: int | None = None


class SearchResponse(BaseModel):
    answer: str | None
    answerable: bool
    threshold: float
    items: list[SearchResult]
    retrieval_ms: float | None = None
    reranked: bool = False
    cache_hit: bool = False
