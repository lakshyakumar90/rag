"""Invitation acceptance endpoint."""

from typing import Annotated

from fastapi import APIRouter, Depends

from api.v1.dependencies import CurrentUser, get_workspace_service
from schemas import InvitationAcceptRequest, WorkspaceResponse
from services import WorkspaceService

router = APIRouter(prefix="/invitations", tags=["invitations"])


@router.post(
    "/accept",
    response_model=WorkspaceResponse,
    summary="Accept an invitation by token",
)
async def accept_invitation(
    payload: InvitationAcceptRequest,
    current_user: CurrentUser,
    service: Annotated[WorkspaceService, Depends(get_workspace_service)],
) -> WorkspaceResponse:
    return await service.accept(payload.token, current_user)
