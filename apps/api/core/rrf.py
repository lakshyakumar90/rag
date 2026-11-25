"""Reciprocal rank fusion for merging ranked retrieval lists."""

from repositories import ScoredChunk


def reciprocal_rank_fusion(
    *rankings: list[ScoredChunk], k: int = 60, max_score: float = 1.0
) -> list[ScoredChunk]:
    """Fuse ranked lists by 1/(k + rank), preserving raw RRF and per-source ranks.

    The first ranking is treated as dense/vector search and the second as
    lexical/keyword search for diagnostic metadata (`dense_rank`, `lexical_rank`,
    `dense_score`, `lexical_score`, `rrf_score`). Normalized `score` maps
    rank-1 in a single list to 1.0 so relative ordering is preserved while
    abstention gating uses calibrated reranker or raw similarity signals.
    """
    best_possible = 1.0 / (k + 1)
    totals: dict[object, float] = {}
    items: dict[object, ScoredChunk] = {}
    dense_ranks: dict[object, int] = {}
    lexical_ranks: dict[object, int] = {}
    dense_scores: dict[object, float] = {}
    lexical_scores: dict[object, float] = {}

    for list_index, ranking in enumerate(rankings):
        for rank, item in enumerate(ranking, start=1):
            totals[item.chunk_id] = totals.get(item.chunk_id, 0.0) + 1.0 / (k + rank)
            items.setdefault(item.chunk_id, item)
            if list_index == 0 and item.chunk_id not in dense_ranks:
                dense_ranks[item.chunk_id] = rank
                dense_scores[item.chunk_id] = item.score
            elif list_index == 1 and item.chunk_id not in lexical_ranks:
                lexical_ranks[item.chunk_id] = rank
                lexical_scores[item.chunk_id] = item.score

    fused = []
    for chunk_id, total in totals.items():
        item = items[chunk_id]
        fused.append(
            ScoredChunk(
                chunk_id=item.chunk_id,
                document_id=item.document_id,
                filename=item.filename,
                content=item.content,
                page_number=item.page_number,
                heading_path=item.heading_path,
                score=min(max_score, total / best_possible),
                dense_rank=dense_ranks.get(chunk_id, item.dense_rank),
                lexical_rank=lexical_ranks.get(chunk_id, item.lexical_rank),
                dense_score=dense_scores.get(chunk_id, item.dense_score),
                lexical_score=lexical_scores.get(chunk_id, item.lexical_score),
                rrf_score=round(total, 6),
                rerank_score=item.rerank_score,
            )
        )
    return sorted(fused, key=lambda item: item.score, reverse=True)
