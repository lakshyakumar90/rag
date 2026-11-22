"""Conversation and message schemas."""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class ConversationCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str | None = Field(default=None, max_length=200)
    # Optional per-conversation override; null keeps the Settings default.
    provider: str | None = Field(default=None, max_length=100)
    model: str | None = Field(default=None, max_length=160)


class ConversationSelectionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: str | None = Field(default=None, max_length=100)
    model: str | None = Field(default=None, max_length=160)


class ConversationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    workspace_id: uuid.UUID
    user_id: uuid.UUID
    title: str
    provider: str | None = None
    model: str | None = None
    created_at: datetime
    updated_at: datetime


class MessageResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    conversation_id: uuid.UUID
    sequence: int
    role: str
    content: str
    citations: list | None
    provider: str | None
    model: str | None
    input_tokens: int
    output_tokens: int
    latency_ms: int
    tokens_estimated: bool
    created_at: datetime
