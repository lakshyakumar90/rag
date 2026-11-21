"""BYOK provider-config request/response schemas (never expose the key)."""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

ProviderType = Literal["openai", "openai-compatible", "anthropic", "ollama"]


class ProviderConfigCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider_type: ProviderType
    base_url: str | None = Field(default=None, max_length=512)
    model: str | None = Field(default=None, max_length=100)
    api_key: str = Field(min_length=1, max_length=2048)


class ProviderConfigUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    base_url: str | None = Field(default=None, max_length=512)
    model: str | None = Field(default=None, max_length=100)
    api_key: str | None = Field(default=None, min_length=1, max_length=2048)


class ProviderConfigResponse(BaseModel):
    """Safe representation: encrypted keys and plaintext are never included."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    user_id: uuid.UUID
    provider_type: str
    base_url: str | None
    model: str | None
    key_last4: str
    created_at: datetime
    updated_at: datetime


class ConnectionTestResponse(BaseModel):
    ok: bool
    message: str
    latency_ms: int | None = None
