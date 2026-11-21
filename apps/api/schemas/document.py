"""Document request/response schemas."""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict

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
    page_count: int | None
    chunks_done: int
    chunks_total: int
    created_at: datetime
    updated_at: datetime


class DocumentPage(BaseModel):
    items: list[DocumentResponse]
    total: int
    skip: int
    limit: int


class DownloadUrlResponse(BaseModel):
    url: str
    expires_in: int
