"""Embedding provider interface and Ollama implementation."""

import asyncio
import logging
from typing import Protocol

import httpx

from core.config import Settings, get_settings

logger = logging.getLogger(__name__)


class EmbeddingError(Exception):
    """The embedding service failed or returned an invalid response."""


class EmbeddingProvider(Protocol):
    """Contract for document/query embeddings of a fixed dimension."""

    @property
    def dimension(self) -> int: ...

    async def embed_documents(self, texts: list[str]) -> list[list[float]]: ...

    async def embed_query(self, text: str) -> list[float]: ...


def normalize(vector: list[float]) -> list[float]:
    """L2-normalize a vector; zero vectors are returned unchanged."""
    norm = sum(value * value for value in vector) ** 0.5
    if norm == 0:
        return vector
    return [value / norm for value in vector]


class OllamaEmbeddingProvider:
    """Embeddings via Ollama's `/api/embed`, with batching and retries."""

    def __init__(
        self,
        settings: Settings | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(
            base_url=self._settings.ollama_base_url,
            timeout=self._settings.embedding_timeout_seconds,
        )

    @property
    def dimension(self) -> int:
        return self._settings.embedding_dim

    async def close(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        results: list[list[float]] = []
        batch_size = max(1, self._settings.embedding_batch_size)
        for start in range(0, len(texts), batch_size):
            batch = texts[start : start + batch_size]
            results.extend(await self._embed_batch(batch))
        return results

    async def embed_query(self, text: str) -> list[float]:
        return (await self.embed_documents([text]))[0]

    async def _embed_batch(self, texts: list[str]) -> list[list[float]]:
        payload = {"model": self._settings.ollama_embedding_model, "input": texts}
        last_error: Exception | None = None
        for attempt in range(1, self._settings.embedding_max_retries + 1):
            try:
                response = await self._client.post("/api/embed", json=payload)
            except httpx.HTTPError as exc:  # timeouts, connection errors
                last_error = exc
            else:
                if response.status_code >= 400:
                    reason = response.text[:200]
                    error = EmbeddingError(
                        f"Ollama returned HTTP {response.status_code}: {reason}"
                    )
                    if response.status_code < 500 and response.status_code != 429:
                        raise error  # permanent client error
                    last_error = error
                else:
                    return self._parse(response.json(), len(texts))

            if attempt == self._settings.embedding_max_retries:
                break
            delay = self._settings.embedding_retry_backoff_seconds * (
                2 ** (attempt - 1)
            )
            logger.warning(
                "embedding batch attempt %d failed (%s); retrying in %.1fs",
                attempt,
                last_error,
                delay,
            )
            await asyncio.sleep(delay)
        raise EmbeddingError(f"embedding request failed: {last_error}")

    def _parse(self, data: object, expected: int) -> list[list[float]]:
        vectors = data.get("embeddings") if isinstance(data, dict) else None
        if not isinstance(vectors, list) or len(vectors) != expected:
            raise EmbeddingError(
                "Ollama returned a different number of embeddings than inputs"
            )
        return [self._prepare(vector) for vector in vectors]

    def _prepare(self, vector: object) -> list[float]:
        if not isinstance(vector, list):
            raise EmbeddingError("Ollama returned a non-list embedding")
        try:
            values = [float(value) for value in vector]
        except (TypeError, ValueError) as exc:
            raise EmbeddingError("Ollama returned a non-numeric embedding") from exc
        if len(values) != self.dimension:
            raise EmbeddingError(
                f"embedding dimension {len(values)} != configured {self.dimension}"
            )
        return normalize(values) if self._settings.embedding_normalize else values


# Process-wide provider used by retrieval and the API dependency.
_embedding_provider: OllamaEmbeddingProvider | None = None


def get_embedding_provider() -> EmbeddingProvider:
    global _embedding_provider
    if _embedding_provider is None:
        _embedding_provider = OllamaEmbeddingProvider()
    return _embedding_provider


async def close_embedding_provider() -> None:
    global _embedding_provider
    if _embedding_provider is not None:
        await _embedding_provider.close()
        _embedding_provider = None
