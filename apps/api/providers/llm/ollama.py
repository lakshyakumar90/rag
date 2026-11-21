"""Ollama chat implementation of the normalized LLM interface."""

import json
from collections.abc import AsyncIterator
from typing import Any

import httpx

from core.config import Settings, get_settings
from providers.llm.types import (
    Completion,
    Error,
    Finish,
    FinishReason,
    LLMEvent,
    Messages,
    TextDelta,
    Usage,
)


class OllamaLLMProvider:
    """Chat via Ollama's NDJSON-streaming `/api/chat` endpoint."""

    name = "ollama"

    def __init__(
        self,
        settings: Settings | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(
            base_url=self._settings.ollama_base_url,
            timeout=self._settings.llm_timeout_seconds,
        )

    async def close(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    def _payload(self, messages: Messages, opts: dict[str, Any]) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": opts.get("model") or self._settings.ollama_llm_model,
            "messages": [
                {"role": message.role, "content": message.content}
                for message in messages
            ],
            "stream": True,
        }
        if "temperature" in opts:
            payload["options"] = {"temperature": opts["temperature"]}
        if "max_tokens" in opts:
            payload.setdefault("options", {})["num_predict"] = opts["max_tokens"]
        return payload

    async def stream(self, messages: Messages, **opts: Any) -> AsyncIterator[LLMEvent]:
        try:
            async with self._client.stream(
                "POST", "/api/chat", json=self._payload(messages, opts)
            ) as response:
                if response.status_code >= 400:
                    await response.aread()
                    yield Error(
                        message=f"Ollama returned HTTP {response.status_code}",
                        code=str(response.status_code),
                    )
                    return

                usage = Usage()
                async for line in response.aiter_lines():
                    if not line.strip():
                        continue
                    try:
                        data = json.loads(line)
                    except json.JSONDecodeError:
                        yield Error(message=f"invalid JSON from Ollama: {line[:120]}")
                        return

                    if data.get("error"):
                        yield Error(message=str(data["error"]))
                        return

                    content = data.get("message", {}).get("content", "")
                    if content:
                        yield TextDelta(text=content)

                    if data.get("done"):
                        usage = Usage(
                            input_tokens=int(data.get("prompt_eval_count") or 0),
                            output_tokens=int(data.get("eval_count") or 0),
                        )
                        yield usage
                        raw_reason = str(data.get("done_reason") or "stop")
                        reason: FinishReason = (
                            raw_reason
                            if raw_reason in ("stop", "length", "content_filter")
                            else "other"
                        )
                        yield Finish(reason=reason)
        except (httpx.HTTPError, OSError) as exc:
            yield Error(message=f"Ollama request failed: {exc}")

    async def complete(self, messages: Messages, **opts: Any) -> Completion:
        text_parts: list[str] = []
        usage = Usage()
        reason: FinishReason = "stop"
        error: str | None = None
        async for event in self.stream(messages, **opts):
            if isinstance(event, TextDelta):
                text_parts.append(event.text)
            elif isinstance(event, Usage):
                usage = event
            elif isinstance(event, Finish):
                reason = event.reason
            elif isinstance(event, Error):
                error = event.message
        if error:
            raise RuntimeError(error)
        return Completion(text="".join(text_parts), finish_reason=reason, usage=usage)
