"""Chat endpoints: SSE streaming answer plus a non-streaming variant."""

import json
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse

from api.v1.dependencies import (
    MemberContext,
    get_chat_rate_limiter,
    get_chat_service,
)
from core.rate_limit import UserRateLimiter
from providers.cli.registry import create_cli_provider
from providers.llm.types import ChatMessage, ProviderAPIError
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
    limiter: Annotated[UserRateLimiter, Depends(get_chat_rate_limiter)],
) -> StreamingResponse:
    await limiter.check(context.user.id)

    async def events():
        async for event in service.stream_answer(
            context,
            payload.query,
            payload.top_k,
            payload.document_ids,
            payload.provider,
            payload.conversation_id,
            request.is_disconnected,
            model=payload.model,
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
    limiter: Annotated[UserRateLimiter, Depends(get_chat_rate_limiter)],
) -> ChatResponse:
    await limiter.check(context.user.id)
    return await service.answer(
        context,
        payload.query,
        payload.top_k,
        payload.document_ids,
        payload.provider,
        payload.conversation_id,
        model=payload.model,
    )


@router.post("/{workspace_id}/chat/test-provider")
async def test_chat_provider(
    payload: ChatRequest,
    context: MemberContext,
    limiter: Annotated[UserRateLimiter, Depends(get_chat_rate_limiter)],
) -> dict[str, bool | str]:
    await limiter.check(context.user.id)
    if payload.provider not in {"cli-codex", "cli-opencode"}:
        return {"ok": False, "detail": "Select Codex or OpenCode."}
    try:
        provider = create_cli_provider(payload.provider)
        completion = await provider.complete(
            [ChatMessage("system", "Reply with OK. Do not use tools.")],
            model=payload.model,
        )
    except ProviderAPIError as exc:
        return {"ok": False, "detail": str(exc)}
    return (
        {"ok": True, "detail": "Model responded successfully."}
        if completion.text.strip()
        else {"ok": False, "detail": "The CLI returned no text."}
    )
