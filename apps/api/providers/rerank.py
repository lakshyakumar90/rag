"""Optional cross-encoder reranking via a TEI-compatible `/rerank` endpoint."""

import math
from dataclasses import dataclass

import httpx

from core.config import get_settings


def _calibrate_score(raw: float) -> float:
    """Ensure cross-encoder score is calibrated in [0, 1] via sigmoid if needed."""
    if 0.0 <= raw <= 1.0:
        return raw
    # Safeguard for backends returning raw uncalibrated logits.
    if raw >= 0:
        z = math.exp(-raw)
        return 1.0 / (1.0 + z)
    z = math.exp(raw)
    return z / (1.0 + z)


@dataclass(frozen=True)
class RerankScore:
    index: int
    score: float


class Reranker:
    """Scores (query, text) pairs; disabled providers are no-ops."""

    def __init__(self, client: httpx.AsyncClient | None = None) -> None:
        settings = get_settings()
        self.enabled = settings.rerank_enabled and bool(settings.rerank_base_url)
        self._model = settings.rerank_model
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(
            base_url=settings.rerank_base_url,
            timeout=settings.rerank_timeout_seconds,
        )

    async def rerank(self, query: str, texts: list[str]) -> list[RerankScore]:
        if not self.enabled or not texts:
            return [RerankScore(index, 1.0) for index in range(len(texts))]
        payload: dict[str, object] = {"query": query, "texts": texts}
        if self._model:
            payload["model"] = self._model
        response = await self._client.post("/rerank", json=payload)
        response.raise_for_status()
        data = response.json()
        if not isinstance(data, list):
            raise ValueError("rerank endpoint did not return a list")
        return [
            RerankScore(
                index=int(item["index"]),
                score=_calibrate_score(float(item["score"])),
            )
            for item in data
        ]

    async def close(self) -> None:
        if self._owns_client:
            await self._client.aclose()
