"""Anthropic Messages API adapter with its own streaming event format."""

import json
from collections.abc import AsyncIterator
from typing import Any

import httpx

from core.config import Settings, get_settings
from providers.llm.errors import map_http_error
from providers.llm.sse import iter_sse_data
from providers.llm.types import (
    Completion,
    Error,
    Finish,
    FinishReason,
    LLMEvent,
    Messages,
    ProviderAPIError,
    TextDelta,
    Usage,
)


def map_stop_reason(reason: str | None) -> FinishReason:
    if reason in ("end_turn", "stop_sequence"):
        return "stop"
    if reason == "max_tokens":
        return "length"
    return "other"


class AnthropicLLMProvider:
    """Chat via `/v1/messages` with SSE event types from Anthropic."""

    name = "anthropic"

    def __init__(
        self,
        settings: Settings | None = None,
        client: httpx.AsyncClient | None = None,
        *,
        base_url: str | None = None,
        api_key: str | None = None,
        model: str | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._base_url = (base_url or self._settings.anthropic_base_url).rstrip("/")
        self._api_key = (
            api_key if api_key is not None else self._settings.anthropic_api_key
        )
        self._model = model or self._settings.anthropic_model
        self._owns_client = client is None
        self._headers: dict[str, str] = {
            "anthropic-version": "2023-06-01",
        }
        if self._api_key:
            self._headers["x-api-key"] = self._api_key
        self._client = client or httpx.AsyncClient(
            base_url=self._base_url,
            timeout=self._settings.llm_timeout_seconds,
            headers=self._headers,
        )

    async def close(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    def _payload(self, messages: Messages, opts: dict[str, Any]) -> dict[str, Any]:
        # Anthropic takes the system prompt as a top-level field, not a message.
        system = "\n\n".join(
            message.content for message in messages if message.role == "system"
        )
        payload: dict[str, Any] = {
            "model": opts.get("model") or self._model,
            "messages": [
                {"role": message.role, "content": message.content}
                for message in messages
                if message.role in ("user", "assistant")
            ],
            "max_tokens": int(opts.get("max_tokens") or 1024),
            "stream": True,
        }
        if system:
            payload["system"] = system
        for key in ("temperature", "top_p"):
            if key in opts:
                payload[key] = opts[key]
        return payload

    async def stream(self, messages: Messages, **opts: Any) -> AsyncIterator[LLMEvent]:
        try:
            async with self._client.stream(
                "POST",
                "/v1/messages",
                json=self._payload(messages, opts),
                headers=self._headers,
            ) as response:
                if response.status_code >= 400:
                    body = (await response.aread()).decode(errors="replace")
                    raise map_http_error(response.status_code, body, response.headers)

                input_tokens = 0
                output_tokens = 0
                stop_reason: FinishReason = "stop"
                async for data in iter_sse_data(response):
                    try:
                        event = json.loads(data)
                    except json.JSONDecodeError:
                        yield Error(message=f"invalid SSE payload: {data[:120]}")
                        return

                    kind = event.get("type")
                    if kind == "error":
                        error = event.get("error") or {}
                        raise ProviderAPIError(
                            str(error.get("message", error))
                            if isinstance(error, dict)
                            else str(error),
                            code=str(error.get("type"))
                            if isinstance(error, dict)
                            else None,
                        )
                    if kind == "message_start":
                        input_tokens = int(
                            (event.get("message", {}).get("usage") or {}).get(
                                "input_tokens", 0
                            )
                        )
                    elif kind == "content_block_delta":
                        delta = event.get("delta") or {}
                        if delta.get("type") == "text_delta" and delta.get("text"):
                            yield TextDelta(text=delta["text"])
                    elif kind == "message_delta":
                        delta = event.get("delta") or {}
                        if delta.get("stop_reason"):
                            stop_reason = map_stop_reason(delta["stop_reason"])
                        output_tokens = int(
                            (event.get("usage") or {}).get("output_tokens", 0)
                        )
                    elif kind == "message_stop":
                        break
                yield Usage(input_tokens=input_tokens, output_tokens=output_tokens)
                yield Finish(reason=stop_reason)
        except httpx.HTTPError as exc:
            yield Error(message=f"request failed: {exc}")

    async def complete(self, messages: Messages, **opts: Any) -> Completion:
        text: list[str] = []
        usage = Usage()
        reason: FinishReason = "stop"
        async for event in self.stream(messages, **opts):
            if isinstance(event, TextDelta):
                text.append(event.text)
            elif isinstance(event, Usage):
                usage = event
            elif isinstance(event, Finish):
                reason = event.reason
            elif isinstance(event, Error):
                raise ProviderAPIError(event.message)
        return Completion("".join(text), reason, usage)
