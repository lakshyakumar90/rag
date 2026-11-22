"""Settings → AI providers request/response DTOs."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

TestStatus = Literal[
    "success",
    "authentication",
    "unsupported_model",
    "quota",
    "timeout",
    "unavailable",
    "invalid_request",
]


class AIDefaultsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: str = Field(min_length=1, max_length=100)
    model: str | None = Field(default=None, max_length=160)


class AIDefaultsResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    provider: str
    model: str | None
    # True when the values come from a saved user preference.
    saved: bool = False


class ProviderTestRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: str = Field(min_length=1, max_length=100)
    model: str | None = Field(default=None, max_length=160)
    # An existing encrypted BYOK config to use instead of a built-in provider.
    config_id: str | None = None


class ProviderTestResponse(BaseModel):
    ok: bool
    status: TestStatus
    detail: str
    provider: str
    model: str | None = None
    latency_ms: int = 0


class ProviderModelsResponse(BaseModel):
    provider: str
    models: list[str]
    # True when the provider cannot enumerate models and the UI should allow
    # typing an id manually.
    manual_only: bool = False


class ProviderOption(BaseModel):
    id: str
    label: str
    built_in: bool
    available: bool
    discovery: bool
    manual_model: bool
    config_id: str | None = None
    default_model: str | None = None


class ProviderOptionsResponse(BaseModel):
    options: list[ProviderOption]
    defaults: AIDefaultsResponse


__all__ = [
    "AIDefaultsRequest",
    "AIDefaultsResponse",
    "ProviderModelsResponse",
    "ProviderOption",
    "ProviderOptionsResponse",
    "ProviderTestRequest",
    "ProviderTestResponse",
    "TestStatus",
]
