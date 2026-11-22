"""Thin async Qdrant REST client.

The app deliberately uses the HTTP API through the ``httpx`` dependency it already
ships, instead of adding ``qdrant-client`` to the lockfile. Only the small surface
the ingestion worker and retrieval pipeline need is implemented here:

* collection creation with an explicit vector size/distance,
* idempotent point upserts with stable (chunk UUID) ids,
* filtered similarity search,
* filtered/count-based deletion used by re-index, delete and permission changes,
* point counting for the resumable backfill and its verification step.

Every method fails closed: network errors surface as ``QdrantUnavailableError`` so
callers can decide explicitly whether to fall back or report the failure. The
client never logs payloads (they contain document identifiers).
"""

from __future__ import annotations

import logging
import re
import uuid
from collections.abc import Iterable
from typing import Any

import httpx

from core.config import Settings, get_settings

logger = logging.getLogger(__name__)

DEFAULT_COLLECTION = "rag_chunks_ollama-embeddinggemma-768-v1"
_COLLECTION_SAFE = re.compile(r"[^a-zA-Z0-9_-]")


class QdrantError(RuntimeError):
    """Base error for an unusable Qdrant response."""


class QdrantUnavailableError(QdrantError):
    """Qdrant could not be reached or returned a server error."""


class QdrantSchemaError(QdrantError):
    """An existing collection is incompatible with the requested profile."""


def collection_name(profile: str, prefix: str | None = None) -> str:
    """Map an embedding profile id to a stable Qdrant collection name.

    Incompatible profiles (different model, dimension, distance or version)
    must use different ids, so they always get separate collections even when
    their dimensions happen to match.
    """
    prefix = (prefix or get_settings().qdrant_collection_prefix).strip(
        "-_"
    ) or "rag_chunks"
    safe = _COLLECTION_SAFE.sub("-", profile).strip("-")
    return f"{prefix}_{safe or 'default'}"[:200]


def point_id(chunk_id: uuid.UUID | str) -> str:
    """Stable Qdrant point id derived from the PostgreSQL chunk primary key."""
    return str(chunk_id)


class QdrantClient:
    def __init__(
        self,
        settings: Settings | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._owns_client = client is None
        base = self._settings.qdrant_url.rstrip("/")
        headers: dict[str, str] = {}
        if self._settings.qdrant_api_key:
            headers["api-key"] = self._settings.qdrant_api_key
        self._client = client or httpx.AsyncClient(
            base_url=base,
            timeout=self._settings.qdrant_timeout_seconds,
            headers=headers,
        )

    async def close(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def health(self) -> bool:
        try:
            response = await self._client.get("/healthz")
        except httpx.HTTPError as exc:
            raise QdrantUnavailableError(str(exc)) from exc
        return response.status_code == 200

    @staticmethod
    def _check(response: httpx.Response, what: str) -> httpx.Response:
        if response.status_code >= 500:
            raise QdrantUnavailableError(
                f"Qdrant {what} failed ({response.status_code})"
            )
        return response

    @staticmethod
    def _result(response: httpx.Response, what: str) -> Any:
        QdrantClient._check(response, what)
        body = response.json()
        status = body.get("status")
        failed = (
            response.status_code >= 400
            or status == "error"
            or (isinstance(status, dict) and "error" in status)
        )
        if failed:
            detail = status.get("error") if isinstance(status, dict) else status
            detail = str(detail or body.get("result") or response.status_code)
            raise QdrantError(f"Qdrant {what} rejected the request: {detail}")
        return body.get("result")

    async def get_collection(self, name: str) -> dict[str, Any] | None:
        try:
            response = await self._client.get(f"/collections/{name}")
        except httpx.HTTPError as exc:
            raise QdrantUnavailableError(str(exc)) from exc
        if response.status_code == 404:
            return None
        return self._result(response, f"describe {name}")

    async def ensure_collection(
        self, name: str, dimension: int, distance: str = "Cosine"
    ) -> None:
        """Create the collection if absent; reject incompatible existing ones."""
        existing = await self.get_collection(name)
        if existing is None:
            try:
                response = await self._client.put(
                    f"/collections/{name}",
                    json={
                        "vectors": {"size": dimension, "distance": distance},
                        # Keep payload indexes so filtered search stays cheap.
                        "shard_number": 1,
                    },
                )
            except httpx.HTTPError as exc:
                raise QdrantUnavailableError(str(exc)) from exc
            self._result(response, f"create {name}")
            return

        vectors = existing.get("config", {}).get("params", {}).get("vectors", {})
        size = vectors.get("size")
        actual_distance = str(vectors.get("distance", "")).lower()
        if size != dimension or actual_distance != distance.lower():
            raise QdrantSchemaError(
                f"collection {name} is {size}/{actual_distance}, expected "
                f"{dimension}/{distance.lower()}; use a different profile id"
            )

    async def delete_collection(self, name: str) -> None:
        try:
            response = await self._client.delete(f"/collections/{name}")
        except httpx.HTTPError as exc:
            raise QdrantUnavailableError(str(exc)) from exc
        self._result(response, f"delete {name}")

    async def upsert(
        self,
        name: str,
        points: Iterable[dict[str, Any]],
        wait: bool = True,
    ) -> int:
        """Upsert points keyed by stable chunk id. Returns the number written."""
        batch = list(points)
        if not batch:
            return 0
        try:
            response = await self._client.put(
                f"/collections/{name}/points",
                params={"wait": str(wait).lower()},
                json={"points": batch},
            )
        except httpx.HTTPError as exc:
            raise QdrantUnavailableError(str(exc)) from exc
        self._result(response, "upsert")
        return len(batch)

    async def search(
        self,
        name: str,
        vector: list[float],
        limit: int,
        must: list[dict[str, Any]] | None = None,
    ) -> list[dict[str, Any]]:
        """Similarity search with Qdrant filter conditions.

        Returns ``[{"id", "score", "payload"}, ...]``. Text is deliberately not
        trusted from the payload: callers re-read it from PostgreSQL.
        """
        body: dict[str, Any] = {
            "query": vector,
            "limit": limit,
            "with_payload": True,
            "with_vector": False,
        }
        if must:
            body["filter"] = {"must": must}
        try:
            response = await self._client.post(
                f"/collections/{name}/points/query", json=body
            )
        except httpx.HTTPError as exc:
            raise QdrantUnavailableError(str(exc)) from exc
        result = self._result(response, "search")
        if result is None:  # Older servers return a bare points list.
            result = response.json().get("result", [])
        points = result.get("points", []) if isinstance(result, dict) else result
        return [
            {
                "id": item["id"],
                "score": float(item["score"]),
                "payload": item.get("payload") or {},
            }
            for item in points
        ]

    async def count(
        self, name: str, must: list[dict[str, Any]] | None = None, exact: bool = True
    ) -> int:
        body: dict[str, Any] = {"exact": exact}
        if must:
            body["filter"] = {"must": must}
        try:
            response = await self._client.post(
                f"/collections/{name}/points/count", json=body
            )
        except httpx.HTTPError as exc:
            raise QdrantUnavailableError(str(exc)) from exc
        result = self._result(response, "count")
        return int(result.get("count", 0)) if isinstance(result, dict) else 0

    async def delete(
        self,
        name: str,
        *,
        ids: Iterable[str] | None = None,
        must: list[dict[str, Any]] | None = None,
        wait: bool = True,
    ) -> None:
        """Delete points by id or filter. Both are idempotent."""
        body: dict[str, Any] = {}
        if ids is not None:
            body["points"] = list(ids)
        if must:
            body["filter"] = {"must": must}
        if not body:
            return
        try:
            response = await self._client.post(
                f"/collections/{name}/points/delete",
                params={"wait": str(wait).lower()},
                json=body,
            )
        except httpx.HTTPError as exc:
            raise QdrantUnavailableError(str(exc)) from exc
        self._result(response, "delete")


def workspace_filter(workspace_id: uuid.UUID | str) -> dict[str, Any]:
    return {"key": "workspace_id", "match": {"value": str(workspace_id)}}


def document_filter(document_id: uuid.UUID | str) -> dict[str, Any]:
    return {"key": "document_id", "match": {"value": str(document_id)}}


def profile_filter(profile: str) -> dict[str, Any]:
    return {"key": "embedding_profile", "match": {"value": profile}}


def get_qdrant_client() -> QdrantClient:
    """Process-wide client factory (overridable in tests via DI)."""
    return QdrantClient()


_client: QdrantClient | None = None


async def shared_qdrant_client() -> QdrantClient:
    global _client
    if _client is None:
        _client = get_qdrant_client()
    return _client


async def close_qdrant_client() -> None:
    global _client
    if _client is not None:
        await _client.close()
        _client = None
