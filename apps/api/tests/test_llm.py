"""Tests for the normalized LLM interface, events, registry and Ollama adapter."""

import json

import httpx
import pytest

from core.config import get_settings
from providers.llm import (
    ChatMessage,
    Completion,
    Error,
    Finish,
    LLMProvider,
    OllamaLLMProvider,
    TextDelta,
    UnknownProviderError,
    Usage,
    available_providers,
    create_llm_provider,
    register_provider,
)

MESSAGES = [
    ChatMessage(role="system", content="Be brief."),
    ChatMessage(role="user", content="Hi"),
]


def _provider(lines: list[dict], status: int = 200) -> OllamaLLMProvider:
    content = "".join(json.dumps(line) + "\n" for line in lines).encode()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, content=content)

    client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="http://ollama.test"
    )
    return OllamaLLMProvider(settings=get_settings().model_copy(), client=client)


def test_protocol_and_message_types() -> None:
    provider = _provider([])
    assert isinstance(provider, LLMProvider)
    assert MESSAGES[0].role == "system"
    assert Usage(1, 2).total_tokens == 3
    assert Completion("ok", "stop").text == "ok"


async def test_stream_yields_normalized_events_in_order() -> None:
    provider = _provider(
        [
            {"message": {"content": "Hel"}, "done": False},
            {"message": {"content": "lo"}, "done": False},
            {
                "message": {"content": ""},
                "done": True,
                "done_reason": "stop",
                "prompt_eval_count": 10,
                "eval_count": 2,
            },
        ]
    )
    events = [event async for event in provider.stream(MESSAGES)]
    assert [type(event) for event in events] == [TextDelta, TextDelta, Usage, Finish]
    assert (
        "".join(event.text for event in events if isinstance(event, TextDelta))
        == "Hello"
    )
    assert events[2].input_tokens == 10 and events[2].output_tokens == 2
    assert events[3].reason == "stop"


async def test_complete_aggregates_stream_events() -> None:
    provider = _provider(
        [
            {"message": {"content": "Answer"}, "done": False},
            {
                "message": {"content": ""},
                "done": True,
                "done_reason": "length",
                "prompt_eval_count": 4,
                "eval_count": 1,
            },
        ]
    )
    result = await provider.complete(MESSAGES)
    assert result.text == "Answer"
    assert result.finish_reason == "length"
    assert result.usage.total_tokens == 5


async def test_stream_emits_error_event_for_http_failure() -> None:
    provider = _provider([{"error": "model not found"}], status=404)
    events = [event async for event in provider.stream(MESSAGES)]
    assert len(events) == 1
    assert isinstance(events[0], Error)
    assert "404" in events[0].code


async def test_stream_emits_error_for_malformed_json() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"not json\n")

    client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="http://ollama.test"
    )
    provider = OllamaLLMProvider(settings=get_settings().model_copy(), client=client)
    events = [event async for event in provider.stream(MESSAGES)]
    assert len(events) == 1 and isinstance(events[0], Error)


async def test_options_are_mapped_to_ollama_payload() -> None:
    seen: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(request.content))
        return httpx.Response(200, content=b"")

    client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="http://ollama.test"
    )
    provider = OllamaLLMProvider(settings=get_settings().model_copy(), client=client)
    async for _ in provider.stream(MESSAGES, temperature=0.2, max_tokens=64):
        pass

    assert seen[0]["model"] == get_settings().ollama_llm_model
    assert seen[0]["stream"] is True
    assert seen[0]["options"] == {"temperature": 0.2, "num_predict": 64}
    assert [message["role"] for message in seen[0]["messages"]] == ["system", "user"]


def test_registry_creates_builtin_provider() -> None:
    assert "ollama" in available_providers()
    assert isinstance(create_llm_provider(), OllamaLLMProvider)
    with pytest.raises(UnknownProviderError):
        create_llm_provider("does-not-exist")


def test_registry_supports_custom_providers() -> None:
    class FakeProvider:
        name = "fake"

        async def complete(self, messages, **opts):
            return Completion("fake", "stop")

        async def stream(self, messages, **opts):
            yield TextDelta("fake")
            yield Finish("stop")

    register_provider("fake", FakeProvider)
    provider = create_llm_provider("fake")
    assert isinstance(provider, FakeProvider)
    assert "fake" in available_providers()
