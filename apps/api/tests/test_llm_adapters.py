"""Tests for OpenAI-compatible and Anthropic adapters with mocked HTTP."""

import json

import httpx
import pytest

from core.config import get_settings
from providers.llm import (
    AnthropicLLMProvider,
    AuthenticationError,
    ChatMessage,
    ContextLengthError,
    Finish,
    LLMProvider,
    OllamaLLMProvider,
    OpenAICompatibleLLMProvider,
    ProviderAPIError,
    RateLimitError,
    TextDelta,
    Usage,
    create_llm_provider,
)
from providers.llm.errors import map_http_error
from providers.llm.sse import iter_sse_data

MESSAGES = [ChatMessage("system", "Be brief."), ChatMessage("user", "Hello")]


def _client(handler, base_url: str = "http://provider.test") -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url=base_url)


def _settings(**overrides):
    return get_settings().model_copy(update=overrides)


def _sse(chunks: list[dict]) -> bytes:
    payload = "".join(f"data: {json.dumps(chunk)}\n\n" for chunk in chunks)
    return payload.encode()


async def test_sse_parser_handles_comments_and_multiline_data() -> None:
    content = b': ping\nevent: message\ndata: {"a": 1}\n\ndata: line1\ndata: line2\n\n'
    client = _client(lambda request: httpx.Response(200, content=content))
    async with client.stream("POST", "/x") as response:
        events = [event async for event in iter_sse_data(response)]
    assert events == ['{"a": 1}', "line1\nline2"]


def test_http_error_mapping() -> None:
    assert isinstance(
        map_http_error(401, '{"error":{"message":"bad key"}}'), AuthenticationError
    )
    limited = map_http_error(429, "slow down", httpx.Headers({"retry-after": "5"}))
    assert isinstance(limited, RateLimitError) and limited.retry_after == "5"
    assert isinstance(
        map_http_error(400, '{"error":{"message":"maximum context length exceeded"}}'),
        ContextLengthError,
    )
    assert isinstance(map_http_error(500, "boom"), ProviderAPIError)


async def test_openai_stream_events_in_order() -> None:
    content = (
        _sse(
            [
                {"choices": [{"delta": {"content": "Hel"}}]},
                {"choices": [{"delta": {"content": "lo"}}]},
                {"choices": [{"delta": {}, "finish_reason": "stop"}]},
                {"choices": [], "usage": {"prompt_tokens": 7, "completion_tokens": 2}},
            ]
        )
        + b"data: [DONE]\n\n"
    )

    provider = OpenAICompatibleLLMProvider(
        settings=_settings(),
        client=_client(lambda request: httpx.Response(200, content=content)),
    )
    events = [event async for event in provider.stream(MESSAGES)]
    assert [type(event) for event in events] == [TextDelta, TextDelta, Usage, Finish]
    assert (
        "".join(event.text for event in events if isinstance(event, TextDelta))
        == "Hello"
    )
    assert events[2].total_tokens == 9
    assert events[3].reason == "stop"


async def test_openai_complete_and_request_payload() -> None:
    seen: list[dict] = []
    content = _sse(
        [
            {"choices": [{"delta": {"content": "OK"}}]},
            {"choices": [{"delta": {}, "finish_reason": "length"}]},
        ]
    )

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(
            {
                "path": str(request.url.path),
                "auth": request.headers.get("authorization"),
                "body": json.loads(request.content),
            }
        )
        return httpx.Response(200, content=content)

    settings = _settings(
        openai_base_url="https://custom.test/v1/",
        openai_api_key="secret",
        openai_model="custom-model",
    )
    provider = OpenAICompatibleLLMProvider(
        settings=settings, client=_client(handler, "https://custom.test")
    )
    result = await provider.complete(MESSAGES, temperature=0.3, max_tokens=12)

    assert result.text == "OK" and result.finish_reason == "length"
    assert provider.base_url == "https://custom.test/v1"
    # The injected client's base_url is the host root; in production it
    # includes the configured /v1 prefix.
    assert seen[0]["path"] == "/chat/completions"
    assert seen[0]["auth"] == "Bearer secret"
    assert seen[0]["body"]["model"] == "custom-model"
    assert seen[0]["body"]["stream_options"] == {"include_usage": True}
    assert seen[0]["body"]["temperature"] == 0.3
    assert seen[0]["body"]["max_tokens"] == 12


async def test_openai_maps_http_errors() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            429,
            content=b'{"error":{"message":"rate limited"}}',
            headers={"retry-after": "3"},
        )

    provider = OpenAICompatibleLLMProvider(
        settings=_settings(), client=_client(handler)
    )
    with pytest.raises(RateLimitError) as exc:
        await provider.complete(MESSAGES)
    assert exc.value.retry_after == "3"


async def test_anthropic_stream_events_and_system_extraction() -> None:
    seen: list[dict] = []
    content = _sse(
        [
            {"type": "message_start", "message": {"usage": {"input_tokens": 11}}},
            {
                "type": "content_block_delta",
                "delta": {"type": "text_delta", "text": "Hi"},
            },
            {
                "type": "message_delta",
                "delta": {"stop_reason": "max_tokens"},
                "usage": {"output_tokens": 4},
            },
            {"type": "message_stop"},
        ]
    )

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(
            {
                "key": request.headers.get("x-api-key"),
                "version": request.headers.get("anthropic-version"),
                "body": json.loads(request.content),
            }
        )
        return httpx.Response(200, content=content)

    settings = _settings(anthropic_api_key="secret", anthropic_model="claude-test")
    provider = AnthropicLLMProvider(settings=settings, client=_client(handler))
    events = [event async for event in provider.stream(MESSAGES)]

    assert [type(event) for event in events] == [TextDelta, Usage, Finish]
    assert events[0].text == "Hi"
    assert events[1].total_tokens == 15
    assert events[2].reason == "length"
    assert seen[0]["key"] == "secret"
    assert seen[0]["version"] == "2023-06-01"
    assert seen[0]["body"]["system"] == "Be brief."
    assert [message["role"] for message in seen[0]["body"]["messages"]] == ["user"]


async def test_anthropic_maps_auth_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, content=b'{"error":{"message":"invalid key"}}')

    provider = AnthropicLLMProvider(settings=_settings(), client=_client(handler))
    with pytest.raises(AuthenticationError):
        await provider.complete(MESSAGES)


async def test_ollama_stream_parses_ndjson_and_builds_payload() -> None:
    seen: list[dict] = []
    lines = [
        {"message": {"content": "Hel"}},
        {"message": {"content": "lo"}},
        {
            "message": {"content": ""},
            "done": True,
            "prompt_eval_count": 8,
            "eval_count": 2,
            "done_reason": "stop",
        },
    ]
    content = "".join(json.dumps(line) + "\n" for line in lines).encode()

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(request.content))
        return httpx.Response(200, content=content)

    provider = OllamaLLMProvider(
        settings=_settings(ollama_llm_model="local-model"),
        client=_client(handler),
    )
    events = [
        event
        async for event in provider.stream(MESSAGES, temperature=0.2, max_tokens=9)
    ]
    assert [type(event) for event in events] == [TextDelta, TextDelta, Usage, Finish]
    assert (
        "".join(event.text for event in events if isinstance(event, TextDelta))
        == "Hello"
    )
    assert events[2].total_tokens == 10
    assert events[3].reason == "stop"
    assert seen[0]["model"] == "local-model"
    assert seen[0]["stream"] is True
    assert seen[0]["options"] == {"temperature": 0.2, "num_predict": 9}


async def test_ollama_complete_raises_on_stream_error() -> None:
    content = b'{"error":"model not found"}\n'
    provider = OllamaLLMProvider(
        client=_client(lambda r: httpx.Response(200, content=content))
    )
    with pytest.raises(RuntimeError, match="model not found"):
        await provider.complete(MESSAGES)


def test_registry_builds_all_adapters() -> None:
    for name, expected in (
        ("ollama", OllamaLLMProvider),
        ("openai", OpenAICompatibleLLMProvider),
        ("openai-compatible", OpenAICompatibleLLMProvider),
        ("anthropic", AnthropicLLMProvider),
    ):
        provider = create_llm_provider(name)
        assert isinstance(provider, expected)
        assert isinstance(provider, LLMProvider)
