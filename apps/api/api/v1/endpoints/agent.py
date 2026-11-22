"""Agent mode: bounded tool-calling loop streamed as SSE."""

import asyncio
import json
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse

from api.v1.dependencies import (
    AgentService,
    MemberContext,
    get_agent_service,
    get_chat_rate_limiter,
)
from core.rate_limit import UserRateLimiter
from schemas import AgentRequest

router = APIRouter(prefix="/workspaces", tags=["agent"])


def _sse(event: dict) -> str:
    return f"data: {json.dumps(event, ensure_ascii=False, default=str)}\n\n"


@router.post("/{workspace_id}/agent", summary="Run a bounded read-only agent turn")
async def agent(
    payload: AgentRequest,
    request: Request,
    context: MemberContext,
    service: Annotated[AgentService, Depends(get_agent_service)],
    limiter: Annotated[UserRateLimiter, Depends(get_chat_rate_limiter)],
) -> StreamingResponse:
    await limiter.check(context.user.id)

    async def events():
        try:
            async for event in _stream(service, context, payload, request):
                yield _sse(event)
        except Exception as exc:  # noqa: BLE001 - keep the stream well-formed
            yield _sse({"type": "error", "message": str(exc)[:300]})

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


async def _stream(
    service: AgentService,
    context: MemberContext,
    payload: AgentRequest,
    request: Request,
):
    queue: asyncio.Queue[dict] = asyncio.Queue()

    async def on_event(event: dict) -> None:
        await queue.put(event)

    task = asyncio.create_task(
        service.run(context, payload, on_event, request.is_disconnected)
    )
    try:
        while True:
            try:
                event = await asyncio.wait_for(queue.get(), timeout=0.5)
            except TimeoutError:
                if task.done():
                    break
                continue
            yield event
        if not task.done():
            await task
    finally:
        if not task.done():
            task.cancel()
