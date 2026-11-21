"""Grounded chat endpoint: retrieval + prompted answer with citations."""

from typing import Annotated

from fastapi import APIRouter, Depends

from api.v1.dependencies import MemberContext, get_chat_service
from schemas import ChatRequest, ChatResponse
from services import ChatService

router = APIRouter(prefix="/workspaces", tags=["chat"])


@router.post(
    "/{workspace_id}/chat",
    response_model=ChatResponse,
    summary="Answer a question from workspace documents with citations",
)
async def chat(
    payload: ChatRequest,
    context: MemberContext,
    service: Annotated[ChatService, Depends(get_chat_service)],
) -> ChatResponse:
    return await service.answer(
        context,
        payload.query,
        payload.top_k,
        payload.document_ids,
        payload.provider,
    )
