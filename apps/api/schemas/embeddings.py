"""Bring-your-own embedding profile DTOs."""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class EmbeddingProfileCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=3, max_length=120, pattern=r"^[\w.:+-]+$")
    provider: str = Field(min_length=2, max_length=60)
    model: str = Field(min_length=1, max_length=160)
    dimension: int = Field(ge=1, le=8192)
    distance: str = Field(default="Cosine", max_length=20)
    version: int = Field(default=1, ge=1)
    base_url: str | None = None
    # Never returned to the browser; encrypted at rest when stored.
    api_key: str | None = Field(default=None, max_length=2048)


class EmbeddingProfileResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    provider: str
    model: str
    dimension: int
    distance: str
    version: int
    enabled: bool
    validated_at: datetime | None
    has_api_key: bool = False


class EmbeddingProfileValidation(BaseModel):
    ok: bool
    detail: str
    dimension: int | None = None


class WorkspaceProfileSwitch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    profile_name: str = Field(min_length=3, max_length=120)
