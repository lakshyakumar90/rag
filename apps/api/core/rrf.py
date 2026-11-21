"""Reciprocal rank fusion for merging ranked retrieval lists."""

from repositories import ScoredChunk


def reciprocal_rank_fusion(
    *rankings: list[ScoredChunk], k: int = 60, max_score: float = 1.0
) -> list[ScoredChunk]:
    """Fuse ranked lists by 1/(k + rank), normalized so rank-1 scores 1.0.

    Normalization makes the configured score threshold meaningful regardless of
    the fusion constant. Duplicate chunks across lists accumulate their scores.
    """
    best_possible = 1.0 / (k + 1)
    totals: dict[object, float] = {}
    items: dict[object, ScoredChunk] = {}
    for ranking in rankings:
        for rank, item in enumerate(ranking, start=1):
            totals[item.chunk_id] = totals.get(item.chunk_id, 0.0) + 1.0 / (k + rank)
            items.setdefault(item.chunk_id, item)

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
            )
        )
    return sorted(fused, key=lambda item: item.score, reverse=True)
