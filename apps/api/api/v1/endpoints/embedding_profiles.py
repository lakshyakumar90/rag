"""Embedding profile management and workspace switches."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends

from api.v1.dependencies import (
    CurrentUser,
    InviterContext,
    get_embedding_profile_service,
)
from schemas import (
    EmbeddingProfileCreate,
    EmbeddingProfileResponse,
    EmbeddingProfileValidation,
    WorkspaceProfileSwitch,
)
from services.embedding_profiles import EmbeddingProfileService

router = APIRouter(prefix="/embedding-profiles", tags=["embedding-profiles"])


@router.get("", response_model=list[EmbeddingProfileResponse])
async def list_profiles(
    current_user: CurrentUser,
    service: Annotated[EmbeddingProfileService, Depends(get_embedding_profile_service)],
) -> list[EmbeddingProfileResponse]:
    return await service.list()


@router.post("", response_model=EmbeddingProfileResponse, status_code=201)
async def create_profile(
    payload: EmbeddingProfileCreate,
    current_user: CurrentUser,
    service: Annotated[EmbeddingProfileService, Depends(get_embedding_profile_service)],
) -> EmbeddingProfileResponse:
    return await service.create(payload)


@router.post("/{name}/validate", response_model=EmbeddingProfileValidation)
async def validate_profile(
    name: str,
    current_user: CurrentUser,
    service: Annotated[EmbeddingProfileService, Depends(get_embedding_profile_service)],
) -> EmbeddingProfileValidation:
    return await service.validate(name)


@router.delete("/{name}", status_code=204)
async def disable_profile(
    name: str,
    current_user: CurrentUser,
    service: Annotated[EmbeddingProfileService, Depends(get_embedding_profile_service)],
) -> None:
    await service.disable(name)


@router.post("/workspaces/{workspace_id}/switch")
async def switch_profile(
    workspace_id: uuid.UUID,
    payload: WorkspaceProfileSwitch,
    context: InviterContext,
    service: Annotated[EmbeddingProfileService, Depends(get_embedding_profile_service)],
) -> dict:
    """Build the replacement index first; the workspace flips when it is ready."""
    return await service.request_switch(workspace_id, payload.profile_name)
