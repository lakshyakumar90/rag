"""RBAC-safe Redis query cache (exact + partitioned semantic) with TTL eviction."""

from __future__ import annotations

import hashlib
import json
import logging
import time
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import get_settings
from models import QueryCacheEntry
from schemas import SearchResponse

logger = logging.getLogger(__name__)

_hits = 0
_misses = 0
_lookup_seconds = 0.0

_CACHE_TTL_SECONDS = 300


def stats() -> dict[str, float | int]:
    total = _hits + _misses
    return {
        "hits": _hits,
        "misses": _misses,
        "hit_rate": round(_hits / total, 4) if total else 0.0,
        "avg_lookup_ms": round((_lookup_seconds / total) * 1000, 3) if total else 0.0,
    }


def _sha256_json(payload: object) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


class QueryCacheService:
    """RBAC-scoped query cache backed by Redis (TTL eviction) with DB fallback."""

    def __init__(self, session: AsyncSession, redis_client=None) -> None:
        self._session = session
        self._settings = get_settings()
        self._redis = redis_client

    def _get_redis(self):
        if self._redis is not None:
            return self._redis
        try:
            from core.redis import get_redis_client

            return get_redis_client()
        except Exception:
            return None

    @staticmethod
    def doc_filter_hash(document_ids: list[uuid.UUID] | None) -> str:
        return _sha256_json(sorted(str(item) for item in (document_ids or [])))[:16]

    @staticmethod
    def cache_key(
        workspace_id: uuid.UUID,
        query: str,
        document_ids: list[uuid.UUID] | None,
        profile: str | None = None,
        *,
        auth_scope_hash: str | None = None,
        top_k: int | None = None,
    ) -> str:
        settings = get_settings()
        query_hash = _sha256_json(" ".join(query.lower().split()))
        doc_hash = QueryCacheService.doc_filter_hash(document_ids)
        payload = {
            "ws": str(workspace_id),
            "auth": auth_scope_hash or "default",
            "docs": doc_hash,
            "top_k": top_k or settings.retrieval_top_k,
            "candidate_k": settings.retrieval_candidate_k,
            "rrf_k": settings.rrf_k,
            "threshold": settings.retrieval_score_threshold,
            "rerank": settings.rerank_enabled,
            "profile": profile or settings.embedding_profile,
            "q_hash": query_hash,
        }
        return _sha256_json(payload)

    @staticmethod
    def authorization_key(
        user_id: uuid.UUID,
        visible: list[uuid.UUID] | None,
        role: str,
    ) -> str:
        """A change in grants or role produces a different RBAC scope hash."""
        payload = {
            "user": str(user_id),
            "role": role,
            "visible": None
            if visible is None
            else sorted(str(item) for item in visible),
        }
        return _sha256_json(payload)

    @staticmethod
    def _redis_exact_key(workspace_id: uuid.UUID, authorization: str, key: str) -> str:
        return f"qcache:exact:{workspace_id}:{authorization[:24]}:{key}"

    @staticmethod
    def _redis_semantic_bucket(
        workspace_id: uuid.UUID, authorization: str, doc_filter_hash: str
    ) -> str:
        return f"qcache:sem:{workspace_id}:{authorization[:24]}:{doc_filter_hash}"

    @staticmethod
    def _redis_ws_index(workspace_id: uuid.UUID) -> str:
        return f"qcache:ws:{workspace_id}"

    async def get(
        self,
        workspace_id: uuid.UUID,
        key: str,
        authorization: str,
        visible: set[uuid.UUID] | None,
        vector: list[float] | None = None,
        profile: str | None = None,
        doc_filter_hash: str = "all",
    ) -> SearchResponse | None:
        global _hits, _misses, _lookup_seconds
        started = time.monotonic()

        redis = self._get_redis()
        if redis is not None:
            try:
                rkey = self._redis_exact_key(workspace_id, authorization, key)
                raw = await redis.get(rkey)
                if raw is not None:
                    data = json.loads(raw)
                    response = SearchResponse.model_validate(data["response"])
                    response = self._enforce_visible(response, visible)
                    _hits += 1
                    _lookup_seconds += time.monotonic() - started
                    return response

                if self._settings.semantic_cache_enabled and vector:
                    hit = await self._redis_semantic_match(
                        redis,
                        workspace_id,
                        authorization,
                        doc_filter_hash,
                        vector,
                        profile,
                    )
                    if hit is not None:
                        hit = self._enforce_visible(hit, visible)
                        _hits += 1
                        _lookup_seconds += time.monotonic() - started
                        return hit
                _misses += 1
                _lookup_seconds += time.monotonic() - started
                return None
            except Exception as exc:
                logger.debug("Redis cache get fallback to DB: %s", exc)

        # Fallback to SQL table when Redis is unavailable (e.g. SQLite unit tests)
        scoped_key = _sha256_json({"k": key, "a": authorization})
        entry = (
            await self._session.execute(
                select(QueryCacheEntry).where(
                    QueryCacheEntry.workspace_id == workspace_id,
                    QueryCacheEntry.cache_key == scoped_key,
                    QueryCacheEntry.authorization == authorization,
                )
            )
        ).scalar_one_or_none()
        if entry is None and self._settings.semantic_cache_enabled and vector:
            entry = await self._db_semantic_match(
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
        response = self._enforce_visible(
            SearchResponse.model_validate(entry.response_json), visible
        )
        _hits += 1
        entry.hit_count += 1
        await self._session.commit()
        _lookup_seconds += elapsed
        return response

    @staticmethod
    def _enforce_visible(
        response: SearchResponse, visible: set[uuid.UUID] | None
    ) -> SearchResponse:
        if visible is not None:
            response.items = [
                item for item in response.items if item.document_id in visible
            ]
            if not response.items:
                response.answer = "I don't know"
                response.answerable = False
        return response

    async def _redis_semantic_match(
        self,
        redis,
        workspace_id: uuid.UUID,
        authorization: str,
        doc_filter_hash: str,
        vector: list[float],
        profile: str | None,
    ) -> SearchResponse | None:
        bucket = self._redis_semantic_bucket(
            workspace_id, authorization, doc_filter_hash
        )
        raw_items = await redis.hgetall(bucket)
        if not raw_items:
            return None
        target_profile = profile or self._settings.embedding_profile
        norm = sum(v * v for v in vector) ** 0.5
        if not norm:
            return None
        best_resp: SearchResponse | None = None
        best_score = self._settings.semantic_cache_threshold
        for raw_val in raw_items.values():
            try:
                rec = json.loads(raw_val)
            except Exception:
                continue
            if rec.get("profile") != target_profile:
                continue
            other = rec.get("vector") or []
            other_norm = sum(v * v for v in other) ** 0.5
            if not other_norm or len(other) != len(vector):
                continue
            sim = sum(a * b for a, b in zip(vector, other, strict=True)) / (
                norm * other_norm
            )
            if sim > best_score:
                best_score = sim
                best_resp = SearchResponse.model_validate(rec["response"])
        return best_resp

    async def _db_semantic_match(
        self,
        workspace_id: uuid.UUID,
        authorization: str,
        vector: list[float],
        profile: str | None,
    ) -> QueryCacheEntry | None:
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
        doc_filter_hash: str = "all",
    ) -> None:
        body = json.loads(response.model_dump_json())
        target_profile = profile or self._settings.embedding_profile

        redis = self._get_redis()
        if redis is not None:
            try:
                rkey = self._redis_exact_key(workspace_id, authorization, key)
                payload = json.dumps(
                    {"response": body, "profile": target_profile, "vector": vector}
                )
                await redis.setex(rkey, _CACHE_TTL_SECONDS, payload)
                ws_idx = self._redis_ws_index(workspace_id)
                await redis.sadd(ws_idx, rkey)
                await redis.expire(ws_idx, _CACHE_TTL_SECONDS + 60)
                if self._settings.semantic_cache_enabled and vector:
                    bucket = self._redis_semantic_bucket(
                        workspace_id, authorization, doc_filter_hash
                    )
                    await redis.hset(bucket, key, payload)
                    await redis.expire(bucket, _CACHE_TTL_SECONDS)
                    await redis.sadd(ws_idx, bucket)
                return
            except Exception as exc:
                logger.debug("Redis cache put fallback to DB: %s", exc)

        now = datetime.now(UTC)
        scoped_key = _sha256_json({"k": key, "a": authorization})
        entry = (
            await self._session.execute(
                select(QueryCacheEntry).where(
                    QueryCacheEntry.workspace_id == workspace_id,
                    QueryCacheEntry.cache_key == scoped_key,
                    QueryCacheEntry.authorization == authorization,
                )
            )
        ).scalar_one_or_none()
        if entry is None:
            self._session.add(
                QueryCacheEntry(
                    workspace_id=workspace_id,
                    cache_key=scoped_key,
                    authorization=authorization,
                    response_json=body,
                    expires_at=now + timedelta(seconds=_CACHE_TTL_SECONDS),
                    query_embedding=vector,
                    embedding_profile=target_profile,
                )
            )
        else:
            entry.response_json = body
            entry.expires_at = now + timedelta(seconds=_CACHE_TTL_SECONDS)
            if vector is not None:
                entry.query_embedding = vector
            entry.embedding_profile = target_profile
        await self._session.commit()

    async def invalidate_workspace(self, workspace_id: uuid.UUID) -> None:
        """Evict all cached entries for a workspace on document/grant/index changes."""
        redis = self._get_redis()
        if redis is not None:
            try:
                ws_idx = self._redis_ws_index(workspace_id)
                keys = await redis.smembers(ws_idx)
                if keys:
                    await redis.delete(*list(keys), ws_idx)
                else:
                    await redis.delete(ws_idx)
            except Exception as exc:
                logger.debug("Redis cache invalidate skipped: %s", exc)

        await self._session.execute(
            delete(QueryCacheEntry).where(QueryCacheEntry.workspace_id == workspace_id)
        )
        await self._session.commit()
