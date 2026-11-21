"""Tests for the Ollama embedding provider (HTTP mocked, no model server)."""

import httpx
import pytest

from core.config import get_settings
from providers.embeddings import EmbeddingError, OllamaEmbeddingProvider, normalize

DIM = 4


def _vector(seed: int) -> list[float]:
    return [float(seed + index) for index in range(DIM)]


def _client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="http://ollama.test"
    )


def _provider(handler=None, **overrides) -> OllamaEmbeddingProvider:
    # Copy the cached settings so tests cannot leak overrides into each other.
    settings = get_settings().model_copy(update=overrides)
    client = _client(handler) if handler else None
    return OllamaEmbeddingProvider(settings=settings, client=client)


def test_normalize_produces_unit_vectors() -> None:
    result = normalize([3.0, 4.0])
    assert result == pytest.approx([0.6, 0.8])
    assert normalize([0.0, 0.0]) == [0.0, 0.0]


async def test_embed_documents_batches_requests() -> None:
    seen: list[list[str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        payload = request.read().decode()
        import json

        inputs = json.loads(payload)["input"]
        seen.append(inputs)
        return httpx.Response(
            200, json={"embeddings": [_vector(i) for i in range(len(inputs))]}
        )

    provider = _provider(handler, embedding_dim=DIM, embedding_batch_size=2)
    vectors = await provider.embed_documents([f"text {i}" for i in range(5)])
    assert len(vectors) == 5
    assert len(seen) == 3  # 2 + 2 + 1
    assert [len(batch) for batch in seen] == [2, 2, 1]
    # Vectors are normalized by default.
    assert sum(v * v for v in vectors[0]) == pytest.approx(1.0)


async def test_embed_query_uses_same_path() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"embeddings": [_vector(1)]})

    provider = _provider(handler, embedding_dim=DIM)
    vector = await provider.embed_query("a query")
    assert len(vector) == DIM
    assert vector == pytest.approx(normalize(_vector(1)))
    assert provider.dimension == DIM


async def test_empty_input_does_not_call_server() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        pytest.fail("should not call the server")

    provider = _provider(handler)
    assert await provider.embed_documents([]) == []


async def test_dimension_mismatch_is_permanent_error() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, json={"embeddings": [[1.0, 2.0]]})

    provider = _provider(handler, embedding_dim=DIM)
    with pytest.raises(EmbeddingError, match="dimension"):
        await provider.embed_documents(["text"])
    assert calls == 1


async def test_client_error_is_not_retried() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(404, text="model not found")

    provider = _provider(handler, embedding_dim=DIM)
    with pytest.raises(EmbeddingError, match="HTTP 404"):
        await provider.embed_documents(["text"])
    assert calls == 1


async def test_server_error_is_retried_with_backoff() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(503, text="busy")
        return httpx.Response(200, json={"embeddings": [_vector(2)]})

    provider = _provider(
        handler,
        embedding_dim=DIM,
        embedding_max_retries=3,
        embedding_retry_backoff_seconds=0,
    )
    vector = await provider.embed_query("text")
    assert calls == 2 and len(vector) == DIM


async def test_timeout_is_retried_then_raises() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        raise httpx.ReadTimeout("timed out")

    provider = _provider(
        handler,
        embedding_dim=DIM,
        embedding_max_retries=2,
        embedding_retry_backoff_seconds=0,
    )
    with pytest.raises(EmbeddingError, match="embedding request failed"):
        await provider.embed_documents(["text"])
    assert calls == 2


async def test_wrong_number_of_embeddings_is_rejected() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"embeddings": []})

    provider = _provider(handler, embedding_dim=DIM)
    with pytest.raises(EmbeddingError, match="different number"):
        await provider.embed_documents(["text"])
