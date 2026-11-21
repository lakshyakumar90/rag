"""BYOK provider configuration endpoints (keys are write-only)."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, status

from api.v1.dependencies import CurrentUser, get_provider_config_service
from schemas import (
    ConnectionTestResponse,
    ProviderConfigCreate,
    ProviderConfigResponse,
    ProviderConfigUpdate,
)
from services import ProviderConfigService

router = APIRouter(prefix="/provider-configs", tags=["provider-configs"])


@router.post(
    "",
    response_model=ProviderConfigResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Save an encrypted provider API key",
)
async def create_config(
    payload: ProviderConfigCreate,
    current_user: CurrentUser,
    service: Annotated[ProviderConfigService, Depends(get_provider_config_service)],
) -> ProviderConfigResponse:
    return await service.create(current_user, payload)


@router.get(
    "",
    response_model=list[ProviderConfigResponse],
    summary="List the current user's provider configurations",
)
async def list_configs(
    current_user: CurrentUser,
    service: Annotated[ProviderConfigService, Depends(get_provider_config_service)],
) -> list[ProviderConfigResponse]:
    return await service.list_for_user(current_user.id)


@router.get(
    "/{config_id}",
    response_model=ProviderConfigResponse,
    summary="Get one provider configuration",
)
async def get_config(
    config_id: uuid.UUID,
    current_user: CurrentUser,
    service: Annotated[ProviderConfigService, Depends(get_provider_config_service)],
) -> ProviderConfigResponse:
    return await service.get(current_user.id, config_id)


@router.patch(
    "/{config_id}",
    response_model=ProviderConfigResponse,
    summary="Update a provider configuration (rotate the key by supplying api_key)",
)
async def update_config(
    config_id: uuid.UUID,
    payload: ProviderConfigUpdate,
    current_user: CurrentUser,
    service: Annotated[ProviderConfigService, Depends(get_provider_config_service)],
) -> ProviderConfigResponse:
    return await service.update(current_user.id, config_id, payload)


@router.post(
    "/{config_id}/test",
    response_model=ConnectionTestResponse,
    summary="Test the saved provider credentials with a one-token request",
)
async def test_config(
    config_id: uuid.UUID,
    current_user: CurrentUser,
    service: Annotated[ProviderConfigService, Depends(get_provider_config_service)],
) -> ConnectionTestResponse:
    return await service.test_connection(current_user.id, config_id)


@router.delete(
    "/{config_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a provider configuration",
)
async def delete_config(
    config_id: uuid.UUID,
    current_user: CurrentUser,
    service: Annotated[ProviderConfigService, Depends(get_provider_config_service)],
) -> None:
    await service.delete(current_user.id, config_id)
