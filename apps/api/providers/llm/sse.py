"""Minimal hand-rolled SSE frame parser (no third-party SSE dependency)."""

from collections.abc import AsyncIterator

import httpx


async def iter_sse_data(response: httpx.Response) -> AsyncIterator[str]:
    """Yield the concatenated ``data:`` payload of each SSE event.

    Comment/keepalive lines (``: ping``) and non-data fields (``event:``,
    ``id:``, ``retry:``) are ignored; a blank line terminates an event.
    """
    parts: list[str] = []
    async for line in response.aiter_lines():
        if not line.strip():
            if parts:
                yield "\n".join(parts)
                parts = []
            continue
        if line.startswith(":"):
            continue
        if line.startswith("data:"):
            parts.append(line[5:].lstrip(" "))
    if parts:
        yield "\n".join(parts)
