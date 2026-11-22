"""Exact-query cache scoped by workspace, authorization and retrieval settings."""

from __future__ import annotations

import hashlib
import json
import time
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import get_settings
from models import QueryCacheEntry
from schemas import SearchResponse

# Single-process counters; adequate for the local stack and documented as such.
_hits = 0
_misses = 0
_lookup_seconds = 0.0


def stats() -> dict[str, float | int]:
    total = _hits + _misses
    return {
        "hits": _hits,
        "misses": _misses,
        "hit_rate": round(_hits / total, 4) if total else 0.0,
        "avg_lookup_ms": round((_lookup_seconds / total) * 1000, 3) if total else 0.0,
    }


class QueryCacheService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._settings = get_settings()

    @staticmethod
    def cache_key(
        workspace_id: uuid.UUID,
        query: str,
        document_ids: list[uuid.UUID] | None,
        profile: str | None = None,
    ) -> str:
        settings = get_settings()
        payload = {
            "q": " ".join(query.lower().split()),
            "documents": sorted(str(item) for item in (document_ids or [])),
            "candidate_k": settings.retrieval_candidate_k,
            "top_k": settings.retrieval_top_k,
            "rrf_k": settings.rrf_k,
            "threshold": settings.retrieval_score_threshold,
            "rerank": settings.rerank_enabled,
            "profile": profile or settings.embedding_profile,
        }
        return hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()

    @staticmethod
    def authorization_key(
        user_id: uuid.UUID,
        visible: list[uuid.UUID] | None,
        role: str,
    ) -> str:
        """A change in grants or role produces a different scope."""
        payload = {
            "user": str(user_id),
            "role": role,
            "visible": None
            if visible is None
            else sorted(str(item) for item in visible),
        }
        return hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()

    async def get(
        self,
        workspace_id: uuid.UUID,
        key: str,
        authorization: str,
        visible: set[uuid.UUID] | None,
        vector: list[float] | None = None,
        profile: str | None = None,
    ) -> SearchResponse | None:
        global _hits, _misses, _lookup_seconds
        started = time.monotonic()
        entry = (
            await self._session.execute(
                select(QueryCacheEntry).where(
                    QueryCacheEntry.workspace_id == workspace_id,
                    QueryCacheEntry.cache_key == key,
                    QueryCacheEntry.authorization == authorization,
                )
            )
        ).scalar_one_or_none()
        if entry is None and self._settings.semantic_cache_enabled and vector:
            entry = await self._semantic_match(
                workspace_id, authorization, vector, profile
            )
        elapsed = time.monotonic() - started
        if entry is None:
            _misses += 1
            _lookup_seconds += elapsed
            return None
        expires = entry.expires_at
        if expires is not None and expires.tzinfo is None:
            expires = expires.replace(tzinfo=UTC)
        if expires and expires < datetime.now(UTC):
            await self._session.delete(entry)
            await self._session.commit()
            _misses += 1
            _lookup_seconds += elapsed
            return None
        response = SearchResponse.model_validate(entry.response_json)
        # Never serve a citation whose document access was revoked meanwhile.
        if visible is not None:
            response.items = [
                item for item in response.items if item.document_id in visible
            ]
            if not response.items:
                response.answer = "I don't know"
                response.answerable = False
        _hits += 1
        entry.hit_count += 1
        await self._session.commit()
        _lookup_seconds += elapsed
        return response

    async def _semantic_match(
        self,
        workspace_id: uuid.UUID,
        authorization: str,
        vector: list[float],
        profile: str | None,
    ) -> QueryCacheEntry | None:
        """Only a high-similarity hit in the same scoped profile is reused."""
        candidates = (
            (
                await self._session.execute(
                    select(QueryCacheEntry).where(
                        QueryCacheEntry.workspace_id == workspace_id,
                        QueryCacheEntry.authorization == authorization,
                        QueryCacheEntry.embedding_profile
                        == (profile or self._settings.embedding_profile),
                        QueryCacheEntry.query_embedding.is_not(None),
                    )
                )
            )
            .scalars()
            .all()
        )
        best: QueryCacheEntry | None = None
        best_score = self._settings.semantic_cache_threshold
        norm = sum(value * value for value in vector) ** 0.5
        if not norm:
            return None
        for candidate in candidates:
            other = candidate.query_embedding or []
            other_norm = sum(value * value for value in other) ** 0.5
            if not other_norm or len(other) != len(vector):
                continue
            score = sum(a * b for a, b in zip(vector, other, strict=True)) / (
                norm * other_norm
            )
            if score > best_score:
                best, best_score = candidate, score
        return best

    async def put(
        self,
        workspace_id: uuid.UUID,
        key: str,
        authorization: str,
        response: SearchResponse,
        vector: list[float] | None = None,
        profile: str | None = None,
    ) -> None:
        now = datetime.now(UTC)
        entry = (
            await self._session.execute(
                select(QueryCacheEntry).where(
                    QueryCacheEntry.workspace_id == workspace_id,
                    QueryCacheEntry.cache_key == key,
                    QueryCacheEntry.authorization == authorization,
                )
            )
        ).scalar_one_or_none()
        body = json.loads(response.model_dump_json())
        if entry is None:
            self._session.add(
                QueryCacheEntry(
                    workspace_id=workspace_id,
                    cache_key=key,
                    authorization=authorization,
                    response_json=body,
                    expires_at=now + timedelta(seconds=300),
                    query_embedding=vector,
                    embedding_profile=profile or self._settings.embedding_profile,
                )
            )
        else:
            entry.response_json = body
            entry.expires_at = now + timedelta(seconds=300)
            if vector is not None:
                entry.query_embedding = vector
            entry.embedding_profile = profile or self._settings.embedding_profile
        await self._session.commit()

    async def invalidate_workspace(self, workspace_id: uuid.UUID) -> None:
        """Call on any document, grant or index change."""
        await self._session.execute(
            delete(QueryCacheEntry).where(QueryCacheEntry.workspace_id == workspace_id)
        )
        await self._session.commit()
