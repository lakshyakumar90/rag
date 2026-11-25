"""Schemas for 4-tier cognitive memory CRUD and consolidation."""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

MemoryTier = Literal["semantic", "episodic", "procedural"]
MemoryStatus = Literal["active", "superseded"]


class MemoryCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tier: MemoryTier = "semantic"
    content: str = Field(min_length=1, max_length=4000)
    confidence: float = Field(default=0.9, ge=0.0, le=1.0)


class MemoryUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    content: str | None = Field(default=None, min_length=1, max_length=4000)
    status: MemoryStatus | None = None
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)


class MemoryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    workspace_id: uuid.UUID
    user_id: uuid.UUID | None
    tier: str
    content: str
    status: str
    superseded_by_id: uuid.UUID | None
    confidence: float
    created_at: datetime
    updated_at: datetime
