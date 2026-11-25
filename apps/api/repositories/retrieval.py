"""Workspace-scoped vector and keyword search over document chunks."""

import uuid
from dataclasses import dataclass

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from models import Document, DocumentChunk, DocumentStatus


@dataclass(frozen=True)
class ScoredChunk:
    chunk_id: uuid.UUID
    document_id: uuid.UUID
    filename: str
    content: str
    page_number: int | None
    heading_path: list[str] | None
    score: float
    dense_rank: int | None = None
    lexical_rank: int | None = None
    dense_score: float | None = None
    lexical_score: float | None = None
    rrf_score: float | None = None
    rerank_score: float | None = None
    parent_content: str | None = None
    context_header: str | None = None
    char_start: int | None = None
    char_end: int | None = None


def _filter_clause(document_ids: list[uuid.UUID] | None) -> tuple[str, dict]:
    if not document_ids:
        return "", {}
    binds = {f"doc_{index}": value for index, value in enumerate(document_ids)}
    names = ", ".join(f":{name}" for name in binds)
    return f"AND dc.document_id IN ({names})", binds


def _cosine(left: list[float], right: list[float]) -> float:
    dot = sum(a * b for a, b in zip(left, right, strict=False))
    left_norm = sum(a * a for a in left) ** 0.5
    right_norm = sum(b * b for b in right) ** 0.5
    if not left_norm or not right_norm:
        return 0.0
    return dot / (left_norm * right_norm)


def _vector_literal(vector: list[float]) -> str:
    return "[" + ",".join(f"{value:.8g}" for value in vector) + "]"


def _positive(items: list[ScoredChunk]) -> list[ScoredChunk]:
    """Drop non-matches; a zero/negative score is not evidence of relevance."""
    return [item for item in items if item.score > 0]


class RetrievalRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def vector_search(
        self,
        workspace_id: uuid.UUID,
        vector: list[float],
        limit: int,
        document_ids: list[uuid.UUID] | None = None,
    ) -> list[ScoredChunk]:
        bind: dict = {
            "workspace_id": workspace_id,
            "vector": _vector_literal(vector),
            "limit": limit,
            "ready": DocumentStatus.READY.value,
        }
        clause, doc_binds = _filter_clause(document_ids)
        bind.update(doc_binds)

        if (
            self._session.bind is not None
            and self._session.bind.dialect.name == "sqlite"
        ):
            # SQLite has no pgvector: score JSON vectors in Python.
            result = await self._session.execute(
                select(DocumentChunk, Document.filename)
                .join(Document, Document.id == DocumentChunk.document_id)
                .where(
                    DocumentChunk.workspace_id == workspace_id,
                    Document.status == DocumentStatus.READY,
                    DocumentChunk.embedding.is_not(None),
                    *(
                        [DocumentChunk.document_id.in_(document_ids)]
                        if document_ids
                        else []
                    ),
                )
            )
            scored = [
                ScoredChunk(
                    chunk_id=chunk.id,
                    document_id=chunk.document_id,
                    filename=filename,
                    content=chunk.content,
                    page_number=chunk.page_number,
                    heading_path=chunk.heading_path,
                    score=_cosine(vector, chunk.embedding or []),
                    parent_content=chunk.parent_content,
                    context_header=chunk.context_header,
                    char_start=chunk.char_start,
                    char_end=chunk.char_end,
                )
                for chunk, filename in result.all()
            ]
            return sorted(_positive(scored), key=lambda item: item.score, reverse=True)[
                :limit
            ]

        sql = text(
            f"""
            SELECT dc.id, dc.document_id, d.filename, dc.content, dc.page_number,
                   dc.heading_path, 1 - (dc.embedding <=> :vector) AS score,
                   dc.parent_content, dc.context_header, dc.char_start, dc.char_end
            FROM document_chunks dc
            JOIN documents d ON d.id = dc.document_id
            WHERE dc.workspace_id = :workspace_id
              AND d.status = :ready
              AND dc.embedding IS NOT NULL
              {clause}
            ORDER BY dc.embedding <=> :vector
            LIMIT :limit
            """
        )
        rows = (await self._session.execute(sql, bind)).all()
        return _positive([self._from_row(row) for row in rows])

    async def keyword_search(
        self,
        workspace_id: uuid.UUID,
        query: str,
        limit: int,
        document_ids: list[uuid.UUID] | None = None,
    ) -> list[ScoredChunk]:
        bind: dict = {
            "workspace_id": workspace_id,
            "query": query,
            "limit": limit,
            "ready": DocumentStatus.READY.value,
        }
        clause, doc_binds = _filter_clause(document_ids)
        bind.update(doc_binds)

        if (
            self._session.bind is not None
            and self._session.bind.dialect.name == "sqlite"
        ):
            result = await self._session.execute(
                select(DocumentChunk, Document.filename)
                .join(Document, Document.id == DocumentChunk.document_id)
                .where(
                    DocumentChunk.workspace_id == workspace_id,
                    Document.status == DocumentStatus.READY,
                    *(
                        [DocumentChunk.document_id.in_(document_ids)]
                        if document_ids
                        else []
                    ),
                )
            )
            terms = {term.lower() for term in query.split() if len(term) > 1}
            scored = []
            for chunk, filename in result.all():
                searchable = (
                    f"{chunk.context_header or ''} {chunk.content}".lower()
                )
                matches = sum(1 for term in terms if term in searchable)
                if matches:
                    scored.append(
                        ScoredChunk(
                            chunk_id=chunk.id,
                            document_id=chunk.document_id,
                            filename=filename,
                            content=chunk.content,
                            page_number=chunk.page_number,
                            heading_path=chunk.heading_path,
                            score=matches / max(1, len(terms)),
                            parent_content=chunk.parent_content,
                            context_header=chunk.context_header,
                            char_start=chunk.char_start,
                            char_end=chunk.char_end,
                        )
                    )
            return sorted(_positive(scored), key=lambda item: item.score, reverse=True)[
                :limit
            ]

        sql = text(
            f"""
            SELECT dc.id, dc.document_id, d.filename, dc.content, dc.page_number,
                   dc.heading_path,
                   ts_rank_cd(dc.search_vector,
                              websearch_to_tsquery('english', :query)) AS score,
                   dc.parent_content, dc.context_header, dc.char_start, dc.char_end
            FROM document_chunks dc
            JOIN documents d ON d.id = dc.document_id
            WHERE dc.workspace_id = :workspace_id
              AND d.status = :ready
              AND dc.search_vector @@ websearch_to_tsquery('english', :query)
              {clause}
            ORDER BY score DESC
            LIMIT :limit
            """
        )
        rows = (await self._session.execute(sql, bind)).all()
        return _positive([self._from_row(row) for row in rows])

    async def verify_qdrant_hits(
        self,
        workspace_id: uuid.UUID,
        hits: list[dict],
        document_ids: list[uuid.UUID] | None = None,
        profile: str | None = None,
    ) -> list[ScoredChunk]:
        """Re-authorize and re-read Qdrant hits from PostgreSQL.

        Qdrant is a cache of ids and vectors, never of text or permissions. A
        hit is accepted only if its chunk still exists, belongs to this
        workspace, is in a ready document, matches the active embedding
        profile/index version and passes the caller's document filter.
        """
        if not hits:
            return []
        scores: dict[uuid.UUID, float] = {}
        for hit in hits:
            try:
                chunk_id = uuid.UUID(str(hit["id"]))
            except (ValueError, KeyError, TypeError):
                continue
            scores[chunk_id] = float(hit.get("score", 0.0))
        if not scores:
            return []
        conditions = [
            DocumentChunk.id.in_(list(scores)),
            DocumentChunk.workspace_id == workspace_id,
            Document.status == DocumentStatus.READY,
            DocumentChunk.embedding.is_not(None),
        ]
        if document_ids:
            conditions.append(DocumentChunk.document_id.in_(document_ids))
        result = await self._session.execute(
            select(
                DocumentChunk,
                Document.filename,
                Document.embedding_profile,
                Document.index_version,
            )
            .join(Document, Document.id == DocumentChunk.document_id)
            .where(*conditions)
        )
        verified: list[ScoredChunk] = []
        for chunk, filename, chunk_profile, index_version in result.all():
            payload = next(
                (
                    hit.get("payload") or {}
                    for hit in hits
                    if str(hit.get("id")) == str(chunk.id)
                ),
                {},
            )
            if profile and chunk_profile and chunk_profile != profile:
                continue
            if (
                payload.get("embedding_profile")
                and profile
                and payload["embedding_profile"] != profile
            ):
                continue
            if (
                payload.get("index_version") is not None
                and payload["index_version"] != index_version
            ):
                continue
            if payload.get("workspace_id") and str(payload["workspace_id"]) != str(
                workspace_id
            ):
                continue
            verified.append(
                ScoredChunk(
                    chunk_id=chunk.id,
                    document_id=chunk.document_id,
                    filename=filename,
                    content=chunk.content,
                    page_number=chunk.page_number,
                    heading_path=chunk.heading_path,
                    score=scores[chunk.id],
                    parent_content=chunk.parent_content,
                    context_header=chunk.context_header,
                    char_start=chunk.char_start,
                    char_end=chunk.char_end,
                )
            )
        return sorted(verified, key=lambda item: item.score, reverse=True)

    @staticmethod
    def _from_row(row) -> ScoredChunk:
        return ScoredChunk(
            chunk_id=row[0],
            document_id=row[1],
            filename=row[2],
            content=row[3],
            page_number=row[4],
            heading_path=row[5],
            score=float(row[6]),
            parent_content=row[7] if len(row) > 7 else None,
            context_header=row[8] if len(row) > 8 else None,
            char_start=row[9] if len(row) > 9 else None,
            char_end=row[10] if len(row) > 10 else None,
        )
