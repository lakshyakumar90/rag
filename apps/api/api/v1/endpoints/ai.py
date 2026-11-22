"""Settings endpoints for AI providers, defaults and connection tests."""

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from api.v1.dependencies import CurrentUser
from core.database import get_session
from schemas import (
    AIDefaultsRequest,
    AIDefaultsResponse,
    ProviderModelsResponse,
    ProviderOptionsResponse,
    ProviderTestRequest,
    ProviderTestResponse,
)
from services.ai_settings import AISettingsService
from services.query_cache import stats as cache_stats

router = APIRouter(prefix="/ai", tags=["ai-settings"])


def get_ai_settings_service(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> AISettingsService:
    return AISettingsService(session)


@router.get("/providers", response_model=ProviderOptionsResponse)
async def provider_options(
    current_user: CurrentUser,
    service: Annotated[AISettingsService, Depends(get_ai_settings_service)],
) -> ProviderOptionsResponse:
    """All selectable providers plus the saved defaults, without secrets."""
    return await service.options(current_user.id)


@router.get("/cache-stats", summary="Exact-query cache hit rate and lookup latency")
async def query_cache_stats(current_user: CurrentUser) -> dict:
    return cache_stats()


@router.get("/defaults", response_model=AIDefaultsResponse)
async def get_defaults(
    current_user: CurrentUser,
    service: Annotated[AISettingsService, Depends(get_ai_settings_service)],
) -> AIDefaultsResponse:
    return await service.get_defaults(current_user.id)


@router.put("/defaults", response_model=AIDefaultsResponse)
async def save_defaults(
    payload: AIDefaultsRequest,
    current_user: CurrentUser,
    service: Annotated[AISettingsService, Depends(get_ai_settings_service)],
) -> AIDefaultsResponse:
    return await service.save_defaults(current_user.id, payload.provider, payload.model)


@router.post("/test", response_model=ProviderTestResponse)
async def test_provider(
    payload: ProviderTestRequest,
    current_user: CurrentUser,
    service: Annotated[AISettingsService, Depends(get_ai_settings_service)],
) -> ProviderTestResponse:
    """Small real request with the selected model; errors are classified."""
    return await service.test(
        current_user.id, payload.provider, payload.model, payload.config_id
    )


@router.get("/models", response_model=ProviderModelsResponse)
async def discover_models(
    provider: str,
    current_user: CurrentUser,
    service: Annotated[AISettingsService, Depends(get_ai_settings_service)],
    config_id: str | None = None,
) -> ProviderModelsResponse:
    return await service.models(current_user.id, provider, config_id)
