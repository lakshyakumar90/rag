"""Account deletion and workspace data export."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, status
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from api.v1.dependencies import (
    CurrentUser,
    MemberContext,
    get_account_service,
)
from core.database import get_session
from services import AccountService
from services.audit import record as record_audit

router = APIRouter(tags=["account"])


@router.delete(
    "/account",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete the current account and all data it owns",
)
async def delete_account(
    current_user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
    service: Annotated[AccountService, Depends(get_account_service)],
) -> None:
    await record_audit(
        session, current_user, "account.deleted", details={"email": current_user.email}
    )
    await service.delete_account(current_user)


@router.get(
    "/workspaces/{workspace_id}/export",
    summary="Export workspace metadata as JSON (file bytes are not included)",
)
async def export_workspace(
    workspace_id: uuid.UUID,
    context: MemberContext,
    current_user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
    service: Annotated[AccountService, Depends(get_account_service)],
) -> JSONResponse:
    await record_audit(
        session,
        current_user,
        "workspace.exported",
        workspace_id=workspace_id,
        target_type="workspace",
        target_id=workspace_id,
    )
    await session.commit()
    data = await service.export_workspace(workspace_id)
    return JSONResponse(
        content=data,
        headers={
            "Content-Disposition": (
                f'attachment; filename="workspace-{workspace_id}.json"'
            )
        },
    )
