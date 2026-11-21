"""Workspace, membership and invitation endpoints.

Protected routes declare a workspace context dependency instead of resolving
the workspace and checking membership themselves; role checks come from
``require_role``.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, status

from api.v1.dependencies import (
    CurrentUser,
    InviterContext,
    MemberContext,
    OwnerContext,
    get_workspace_service,
)
from schemas import (
    InvitationCreate,
    InvitationCreatedResponse,
    InvitationResponse,
    MemberResponse,
    RoleUpdate,
    WorkspaceCreate,
    WorkspaceResponse,
    WorkspaceUpdate,
)
from services import WorkspaceService

router = APIRouter(prefix="/workspaces", tags=["workspaces"])


@router.post(
    "",
    response_model=WorkspaceResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a workspace (the creator becomes its owner)",
)
async def create_workspace(
    payload: WorkspaceCreate,
    current_user: CurrentUser,
    service: Annotated[WorkspaceService, Depends(get_workspace_service)],
) -> WorkspaceResponse:
    return await service.create(payload, current_user)


@router.get("", response_model=list[WorkspaceResponse], summary="List my workspaces")
async def list_workspaces(
    current_user: CurrentUser,
    service: Annotated[WorkspaceService, Depends(get_workspace_service)],
) -> list[WorkspaceResponse]:
    return await service.list_mine(current_user.id)


@router.get(
    "/{workspace_id}", response_model=WorkspaceResponse, summary="Get a workspace"
)
async def get_workspace(
    context: MemberContext,
    service: Annotated[WorkspaceService, Depends(get_workspace_service)],
) -> WorkspaceResponse:
    return service.describe(context)


@router.patch(
    "/{workspace_id}",
    response_model=WorkspaceResponse,
    summary="Update a workspace (owner only)",
)
async def update_workspace(
    payload: WorkspaceUpdate,
    context: OwnerContext,
    service: Annotated[WorkspaceService, Depends(get_workspace_service)],
) -> WorkspaceResponse:
    return await service.update(context, payload)


@router.delete(
    "/{workspace_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a workspace (owner only)",
)
async def delete_workspace(
    context: OwnerContext,
    service: Annotated[WorkspaceService, Depends(get_workspace_service)],
) -> None:
    await service.delete(context)


@router.post(
    "/{workspace_id}/invitations",
    response_model=InvitationCreatedResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Invite by email (returns the token/link instead of sending email)",
)
async def invite(
    payload: InvitationCreate,
    context: InviterContext,
    service: Annotated[WorkspaceService, Depends(get_workspace_service)],
) -> InvitationCreatedResponse:
    return await service.invite(context, payload)


@router.get(
    "/{workspace_id}/invitations",
    response_model=list[InvitationResponse],
    summary="List workspace invitations",
)
async def list_invitations(
    context: MemberContext,
    service: Annotated[WorkspaceService, Depends(get_workspace_service)],
) -> list[InvitationResponse]:
    return await service.list_invitations(context)


@router.get(
    "/{workspace_id}/members",
    response_model=list[MemberResponse],
    summary="List workspace members",
)
async def list_members(
    context: MemberContext,
    service: Annotated[WorkspaceService, Depends(get_workspace_service)],
) -> list[MemberResponse]:
    return await service.list_members(context)


@router.patch(
    "/{workspace_id}/members/{user_id}",
    response_model=MemberResponse,
    summary="Change a member's role (owner only)",
)
async def change_member_role(
    user_id: uuid.UUID,
    payload: RoleUpdate,
    context: OwnerContext,
    service: Annotated[WorkspaceService, Depends(get_workspace_service)],
) -> MemberResponse:
    return await service.change_role(context, user_id, payload)


@router.delete(
    "/{workspace_id}/members/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Remove a member (owner only)",
)
async def remove_member(
    user_id: uuid.UUID,
    context: OwnerContext,
    service: Annotated[WorkspaceService, Depends(get_workspace_service)],
) -> None:
    await service.remove_member(context, user_id)
