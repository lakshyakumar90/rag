"""Hybrid retrieval: pgvector + full-text, fused with RRF, with a fallback."""

import logging
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from core.config import get_settings
from core.rrf import reciprocal_rank_fusion
from providers.embeddings import EmbeddingProvider
from providers.rerank import Reranker
from repositories import RetrievalRepository, ScoredChunk
from schemas import SearchResponse, SearchResult
from services.workspaces import WorkspaceContext

logger = logging.getLogger(__name__)


class RetrievalService:
    def __init__(
        self,
        session: AsyncSession,
        embeddings: EmbeddingProvider,
        reranker: Reranker | None = None,
    ) -> None:
        self._repository = RetrievalRepository(session)
        self._embeddings = embeddings
        self._reranker = reranker

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

        vector = await self._embeddings.embed_query(query)
        vector_hits = await self._repository.vector_search(
            workspace_id, vector, candidate_k, document_ids
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
        return SearchResponse(
            answer=None if answerable else "I don't know",
            answerable=answerable,
            threshold=settings.retrieval_score_threshold,
            items=[self._to_result(item) for item in fused],
        )

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
