"""Conversation CRUD and message history endpoints."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, status

from api.v1.dependencies import (
    MemberContext,
    get_chat_service,
    get_conversation_service,
)
from schemas import (
    ChatResponse,
    ConversationCreate,
    ConversationResponse,
    ConversationSelectionRequest,
    MessageResponse,
)
from services import ChatService, ConversationService
from services.chat import publish_cancel_stream

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
    return await service.create(context, payload.title, payload.provider, payload.model)


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


@router.patch(
    "/{workspace_id}/conversations/{conversation_id}",
    response_model=ConversationResponse,
    summary="Rename a conversation",
)
async def rename_conversation(
    conversation_id: uuid.UUID,
    payload: ConversationCreate,
    context: MemberContext,
    service: Annotated[ConversationService, Depends(get_conversation_service)],
) -> ConversationResponse:
    return await service.rename(context, conversation_id, payload.title or "")


@router.patch(
    "/{workspace_id}/conversations/{conversation_id}/selection",
    response_model=ConversationResponse,
    summary="Override the provider/model used by this conversation",
)
async def set_selection(
    conversation_id: uuid.UUID,
    payload: ConversationSelectionRequest,
    context: MemberContext,
    service: Annotated[ConversationService, Depends(get_conversation_service)],
) -> ConversationResponse:
    return await service.set_selection(
        context, conversation_id, payload.provider, payload.model
    )


@router.post(
    "/{workspace_id}/conversations/{conversation_id}/stop",
    summary="Cancel an in-flight streamed answer",
)
async def stop_stream(
    conversation_id: uuid.UUID,
    context: MemberContext,
    service: Annotated[ConversationService, Depends(get_conversation_service)],
) -> dict[str, bool]:
    await service.get(context, conversation_id)  # verify ownership
    return {"cancelled": await publish_cancel_stream(conversation_id)}


@router.post(
    "/{workspace_id}/conversations/{conversation_id}/regenerate",
    response_model=ChatResponse,
    summary="Replace the last answer with a freshly generated one",
)
async def regenerate(
    conversation_id: uuid.UUID,
    context: MemberContext,
    service: Annotated[ChatService, Depends(get_chat_service)],
) -> ChatResponse:
    return await service.regenerate_last(context, conversation_id)


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
