"""Conversation CRUD and message history endpoints."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, status

from api.v1.dependencies import (
    MemberContext,
    get_conversation_service,
)
from schemas import (
    ConversationCreate,
    ConversationResponse,
    MessageResponse,
)
from services import ConversationService

router = APIRouter(prefix="/workspaces", tags=["conversations"])


@router.post(
    "/{workspace_id}/conversations",
    response_model=ConversationResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a conversation",
)
async def create_conversation(
    payload: ConversationCreate,
    context: MemberContext,
    service: Annotated[ConversationService, Depends(get_conversation_service)],
) -> ConversationResponse:
    return await service.create(context, payload.title)


@router.get(
    "/{workspace_id}/conversations",
    response_model=list[ConversationResponse],
    summary="List the current user's conversations in a workspace",
)
async def list_conversations(
    context: MemberContext,
    service: Annotated[ConversationService, Depends(get_conversation_service)],
) -> list[ConversationResponse]:
    return await service.list_for_user(context)


@router.get(
    "/{workspace_id}/conversations/{conversation_id}",
    response_model=ConversationResponse,
    summary="Get one conversation",
)
async def get_conversation(
    conversation_id: uuid.UUID,
    context: MemberContext,
    service: Annotated[ConversationService, Depends(get_conversation_service)],
) -> ConversationResponse:
    return ConversationResponse.model_validate(
        await service.get(context, conversation_id)
    )


@router.get(
    "/{workspace_id}/conversations/{conversation_id}/messages",
    response_model=list[MessageResponse],
    summary="List a conversation's messages",
)
async def list_messages(
    conversation_id: uuid.UUID,
    context: MemberContext,
    service: Annotated[ConversationService, Depends(get_conversation_service)],
) -> list[MessageResponse]:
    return await service.messages(context, conversation_id)


@router.delete(
    "/{workspace_id}/conversations/{conversation_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a conversation and its messages",
)
async def delete_conversation(
    conversation_id: uuid.UUID,
    context: MemberContext,
    service: Annotated[ConversationService, Depends(get_conversation_service)],
) -> None:
    await service.delete(context, conversation_id)
