"""OpenAI-compatible chat adapter (OpenAI, Gemini compat, Ollama, OpenRouter, Groq)."""

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


def map_finish_reason(reason: str | None) -> FinishReason:
    if reason in ("stop", "length", "content_filter"):
        return reason
    return "other"


class OpenAICompatibleLLMProvider:
    """Talks to any `/chat/completions` endpoint with OpenAI-style SSE."""

    name = "openai-compatible"

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
        self._base_url = (base_url or self._settings.openai_base_url).rstrip("/")
        self._api_key = (
            api_key if api_key is not None else self._settings.openai_api_key
        )
        self._model = model or self._settings.openai_model
        self._owns_client = client is None
        self._headers = (
            {"Authorization": f"Bearer {self._api_key}"} if self._api_key else {}
        )
        self._client = client or httpx.AsyncClient(
            base_url=self._base_url,
            timeout=self._settings.llm_timeout_seconds,
            headers=self._headers,
        )

    @property
    def base_url(self) -> str:
        return self._base_url

    async def close(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    def _payload(self, messages: Messages, opts: dict[str, Any]) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": opts.get("model") or self._model,
            "messages": [
                {"role": message.role, "content": message.content}
                for message in messages
            ],
            "stream": True,
            # Ask for usage in the final SSE chunk when the endpoint supports it.
            "stream_options": {"include_usage": True},
        }
        for source, target in (
            ("temperature", "temperature"),
            ("max_tokens", "max_tokens"),
            ("top_p", "top_p"),
        ):
            if source in opts:
                payload[target] = opts[source]
        return payload

    async def stream(self, messages: Messages, **opts: Any) -> AsyncIterator[LLMEvent]:
        try:
            async with self._client.stream(
                "POST",
                "/chat/completions",
                json=self._payload(messages, opts),
                headers=self._headers,
            ) as response:
                if response.status_code >= 400:
                    body = (await response.aread()).decode(errors="replace")
                    raise map_http_error(response.status_code, body, response.headers)

                usage = Usage()
                finish: FinishReason | None = None
                async for data in iter_sse_data(response):
                    if data.strip() == "[DONE]":
                        break
                    try:
                        chunk = json.loads(data)
                    except json.JSONDecodeError:
                        yield Error(message=f"invalid SSE payload: {data[:120]}")
                        return
                    if chunk.get("error"):
                        raise ProviderAPIError(
                            str(chunk["error"].get("message", chunk["error"]))
                            if isinstance(chunk["error"], dict)
                            else str(chunk["error"])
                        )
                    choices = chunk.get("choices") or []
                    if choices:
                        content = (choices[0].get("delta") or {}).get("content")
                        if content:
                            yield TextDelta(text=content)
                        if choices[0].get("finish_reason"):
                            finish = map_finish_reason(choices[0]["finish_reason"])
                    if chunk.get("usage"):
                        raw = chunk["usage"]
                        usage = Usage(
                            input_tokens=int(raw.get("prompt_tokens") or 0),
                            output_tokens=int(raw.get("completion_tokens") or 0),
                        )
                yield usage
                yield Finish(reason=finish or "stop")
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
