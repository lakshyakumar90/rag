"""Hybrid retrieval: pgvector + full-text, fused with RRF, with a fallback."""

import logging
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import get_settings
from core.rrf import reciprocal_rank_fusion
from providers.embeddings import EmbeddingProvider
from providers.qdrant import QdrantError
from providers.rerank import Reranker
from repositories import RetrievalRepository, ScoredChunk
from schemas import SearchResponse, SearchResult
from services.document_access import DocumentAccessService
from services.exceptions import VectorIndexUnavailableError
from services.qdrant_index import QdrantIndexService
from services.query_cache import QueryCacheService
from services.workspaces import WorkspaceContext

logger = logging.getLogger(__name__)


class RetrievalService:
    def __init__(
        self,
        session: AsyncSession,
        embeddings: EmbeddingProvider,
        reranker: Reranker | None = None,
        indexer: QdrantIndexService | None = None,
    ) -> None:
        self._session = session
        self._repository = RetrievalRepository(session)
        self._embeddings = embeddings
        self._reranker = reranker
        self._indexer = indexer

    async def search(
        self,
        context: WorkspaceContext,
        query: str,
        top_k: int | None = None,
        document_ids: list[uuid.UUID] | None = None,
    ) -> SearchResponse:
        settings = get_settings()
        candidate_k = settings.retrieval_candidate_k
        workspace_id = context.workspace.id
        cache = QueryCacheService(self._session)
        role = getattr(context.role, "value", context.role)
        profile = (
            getattr(context.workspace, "active_embedding_profile", None)
            or settings.embedding_profile
        )
        key = cache.cache_key(workspace_id, query, document_ids, profile)

        # Per-document grants are applied before either index is queried, and
        # re-verified against PostgreSQL for Qdrant hits.
        access = DocumentAccessService(self._session)
        role = getattr(context.role, "value", context.role)
        visible = await access.visible_document_ids(
            workspace_id, context.user.id, str(role)
        )
        if visible is not None:
            if document_ids:
                allowed = set(document_ids) & set(visible)
                document_ids = [item for item in document_ids if item in allowed]
            else:
                document_ids = visible
            if not document_ids:
                return SearchResponse(
                    answer="I don't know",
                    answerable=False,
                    threshold=settings.retrieval_score_threshold,
                    items=[],
                )

        authorization = cache.authorization_key(context.user.id, visible, str(role))
        embeddings = await self._embeddings_for(profile, settings)
        vector = await embeddings.embed_query(query)
        if settings.query_cache_enabled:
            hit = await cache.get(
                workspace_id,
                key,
                authorization,
                None if visible is None else set(visible),
                vector=vector,
                profile=profile,
            )
            if hit is not None:
                return hit
        vector_hits = await self._vector_candidates(
            workspace_id, vector, candidate_k, document_ids, settings, profile
        )
        keyword_hits = await self._repository.keyword_search(
            workspace_id, query, candidate_k, document_ids
        )

        fused = reciprocal_rank_fusion(vector_hits, keyword_hits, k=settings.rrf_k)
        fused = await self._rerank(query, fused)
        fused = fused[: top_k or settings.retrieval_top_k]

        answerable = (
            bool(fused) and fused[0].score >= settings.retrieval_score_threshold
        )
        response = SearchResponse(
            answer=None if answerable else "I don't know",
            answerable=answerable,
            threshold=settings.retrieval_score_threshold,
            items=[self._to_result(item) for item in fused],
        )
        if settings.query_cache_enabled:
            await cache.put(workspace_id, key, authorization, response, vector, profile)
        return response

    async def _embeddings_for(self, profile: str, settings):
        if profile == settings.embedding_profile:
            return self._embeddings
        from types import SimpleNamespace

        from core.crypto import decrypt_secret
        from models import EmbeddingProfile
        from providers.embeddings import get_profile_embedding_provider

        stored = (
            await self._session.execute(
                select(EmbeddingProfile).where(EmbeddingProfile.name == profile)
            )
        ).scalar_one_or_none()
        if stored is None:
            return self._embeddings
        config = dict(stored.config_json or {})
        if config.get("encrypted_api_key"):
            config["api_key"] = decrypt_secret(config["encrypted_api_key"])
        return get_profile_embedding_provider(
            SimpleNamespace(
                provider=stored.provider,
                model=stored.model,
                dimension=stored.dimension,
                config_json=config,
            )
        )

    async def _vector_candidates(
        self,
        workspace_id: uuid.UUID,
        vector: list[float],
        candidate_k: int,
        document_ids: list[uuid.UUID] | None,
        settings,
        profile: str | None = None,
    ) -> list[ScoredChunk]:
        """Qdrant similarity first, always verified against PostgreSQL."""
        if not (settings.qdrant_enabled and self._indexer and self._indexer.enabled):
            return await self._repository.vector_search(
                workspace_id, vector, candidate_k, document_ids
            )
        try:
            hits = await self._indexer.search(
                profile or settings.embedding_profile,
                vector,
                candidate_k,
                workspace_id,
                document_ids,
            )
            return await self._repository.verify_qdrant_hits(
                workspace_id, hits, document_ids, profile or settings.embedding_profile
            )
        except QdrantError as exc:
            logger.warning("Qdrant search failed: %s", exc)
            if settings.qdrant_fallback_to_pgvector:
                return await self._repository.vector_search(
                    workspace_id, vector, candidate_k, document_ids
                )
            raise VectorIndexUnavailableError() from exc

    async def _rerank(self, query: str, items: list[ScoredChunk]) -> list[ScoredChunk]:
        if self._reranker is None or not self._reranker.enabled or not items:
            return items
        try:
            scores = await self._reranker.rerank(
                query, [item.content for item in items]
            )
        except Exception as exc:
            # Reranking is an enhancement; a failing service must not break search.
            logger.warning("reranking failed, using fused ranking: %s", exc)
            return items
        reranked = []
        for score in sorted(scores, key=lambda item: item.score, reverse=True):
            if 0 <= score.index < len(items):
                original = items[score.index]
                reranked.append(
                    ScoredChunk(
                        chunk_id=original.chunk_id,
                        document_id=original.document_id,
                        filename=original.filename,
                        content=original.content,
                        page_number=original.page_number,
                        heading_path=original.heading_path,
                        score=score.score,
                    )
                )
        return reranked or items

    @staticmethod
    def _to_result(item: ScoredChunk) -> SearchResult:
        return SearchResult(
            chunk_id=item.chunk_id,
            document_id=item.document_id,
            filename=item.filename,
            text=item.content,
            score=item.score,
            page_number=item.page_number,
            heading_path=item.heading_path,
        )
