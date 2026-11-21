"""Feedback, usage, analytics and audit endpoints."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends

from api.v1.dependencies import (
    AdminContext,
    MemberContext,
    get_feedback_service,
    get_usage_service,
)
from schemas import (
    AnalyticsResponse,
    AuditEntryResponse,
    FeedbackRequest,
    FeedbackResponse,
    UsageResponse,
)
from services import FeedbackService, UsageService

router = APIRouter(prefix="/workspaces", tags=["production"])


@router.post(
    "/{workspace_id}/messages/{message_id}/feedback",
    response_model=FeedbackResponse,
    summary="Rate an assistant answer (thumbs up/down with optional comment)",
)
async def set_feedback(
    message_id: uuid.UUID,
    payload: FeedbackRequest,
    context: MemberContext,
    service: Annotated[FeedbackService, Depends(get_feedback_service)],
) -> FeedbackResponse:
    return await service.set(context, message_id, payload)


@router.get(
    "/{workspace_id}/usage",
    response_model=UsageResponse,
    summary="Query/token/storage totals for the workspace",
)
async def usage(
    context: MemberContext,
    service: Annotated[UsageService, Depends(get_usage_service)],
) -> UsageResponse:
    return await service.usage(context.workspace.id)


@router.get(
    "/{workspace_id}/usage/analytics",
    response_model=AnalyticsResponse,
    summary="Most asked questions, low-confidence answers and top cited documents",
)
async def analytics(
    context: AdminContext,
    service: Annotated[UsageService, Depends(get_usage_service)],
) -> AnalyticsResponse:
    return await service.analytics(context.workspace.id)


@router.get(
    "/{workspace_id}/audit-log",
    response_model=list[AuditEntryResponse],
    summary="Recent sensitive actions in the workspace",
)
async def audit_log(
    context: AdminContext,
    service: Annotated[UsageService, Depends(get_usage_service)],
) -> list[AuditEntryResponse]:
    return await service.audit(context.workspace.id)
