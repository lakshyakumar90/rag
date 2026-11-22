"""Document request/response schemas."""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from models import DocumentStatus


class DocumentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    workspace_id: uuid.UUID
    uploaded_by: uuid.UUID
    filename: str
    mime_type: str
    size: int
    sha256: str
    status: DocumentStatus
    error: str | None
    source_type: str | None = None
    source_url: str | None = None
    source_metadata: dict | None = None
    restricted: bool = False
    page_count: int | None
    ingestion_stage: (
        Literal[
            "uploading",
            "queued",
            "reading",
            "ocr",
            "chunking",
            "embedding",
            "indexing",
            "extracting",  # legacy v1 rows
        ]
        | None
    ) = None
    embedding_profile: str | None = None
    index_version: int = 0
    upload_bytes: int = 0
    upload_total: int = 0
    pages_total: int | None = None
    pages_done: int = 0
    ocr_pages_done: int = 0
    ocr_pages_total: int | None = None
    unreadable_pages: list[int] | None = None
    sections_done: int = 0
    sections_total: int | None = None
    chunks_embedded: int = 0
    chunks_done: int
    chunks_total: int
    chunks_indexed: int = 0
    progress_updated_at: datetime | None = None
    qdrant_synced_at: datetime | None = None
    progress_percent: float | None = None
    created_at: datetime
    updated_at: datetime


class DocumentSnippetResponse(BaseModel):
    text: str
    page_number: int | None
    heading_path: list[str] | None


class DocumentPage(BaseModel):
    items: list[DocumentResponse]
    total: int
    skip: int
    limit: int


class GrantUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    restricted: bool
    user_ids: list[uuid.UUID] = Field(default_factory=list)


class GrantResponse(BaseModel):
    document_id: uuid.UUID
    restricted: bool
    user_ids: list[uuid.UUID]


class DownloadUrlResponse(BaseModel):
    url: str
    expires_in: int
