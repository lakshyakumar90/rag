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
                )
                for chunk, filename in result.all()
            ]
            return sorted(_positive(scored), key=lambda item: item.score, reverse=True)[
                :limit
            ]

        sql = text(
            f"""
            SELECT dc.id, dc.document_id, d.filename, dc.content, dc.page_number,
                   dc.heading_path, 1 - (dc.embedding <=> :vector) AS score
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
                content = chunk.content.lower()
                matches = sum(1 for term in terms if term in content)
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
                              websearch_to_tsquery('english', :query)) AS score
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
        )
