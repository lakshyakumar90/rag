"""Chat endpoints: SSE streaming answer plus a non-streaming variant."""

import json
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse

from api.v1.dependencies import MemberContext, get_chat_service
from schemas import ChatRequest, ChatResponse
from services import ChatService

router = APIRouter(prefix="/workspaces", tags=["chat"])


def _sse(event: dict) -> str:
    return f"data: {json.dumps(event, ensure_ascii=False, default=str)}\n\n"


@router.post(
    "/{workspace_id}/chat",
    summary="Stream a grounded answer as SSE (sources, token, done, error)",
)
async def chat(
    payload: ChatRequest,
    request: Request,
    context: MemberContext,
    service: Annotated[ChatService, Depends(get_chat_service)],
) -> StreamingResponse:
    async def events():
        async for event in service.stream_answer(
            context,
            payload.query,
            payload.top_k,
            payload.document_ids,
            payload.provider,
            payload.conversation_id,
            request.is_disconnected,
        ):
            yield _sse(event)

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post(
    "/{workspace_id}/chat/complete",
    response_model=ChatResponse,
    summary="Non-streaming grounded answer (same pipeline as /chat)",
)
async def chat_complete(
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
        payload.conversation_id,
    )
