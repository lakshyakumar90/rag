"""Lightweight Postgres entity/edge extraction and permission-aware 2-hop retrieval."""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass

from sqlalchemy import delete, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from models.document import Document, DocumentChunk
from models.enums import DocumentStatus
from models.graph import Entity, EntityEdge
from repositories.retrieval import ScoredChunk

_RELATION_PATTERNS = [
    re.compile(
        r"\b([A-Z][A-Za-z0-9._-]*(?:\s+[A-Z0-9][A-Za-z0-9._-]*){0,3})\s+"
        r"(calls|uses|depends on|connects to|writes to|reads from|publishes to|"
        r"authenticates via|stores in|runs on|deployed on|integrates with|"
        r"routes to|owns|manages|replaces)\s+"
        r"([A-Z][A-Za-z0-9._-]*(?:\s+[A-Z0-9][A-Za-z0-9._-]*){0,3})"
    ),
]


@dataclass(frozen=True)
class ExtractedTriple:
    source: str
    relation: str
    target: str
    entity_type: str = "system"


def canonicalize_entity(name: str) -> str:
    """Normalize an entity name into a deterministic canonical key."""
    cleaned = re.sub(r"[^a-z0-9\s._-]", "", name.lower())
    return " ".join(cleaned.split())[:180]


def extract_triples(content: str) -> list[ExtractedTriple]:
    """Extract (source, relation, target) triples from chunk text."""
    triples: list[ExtractedTriple] = []
    seen: set[tuple[str, str, str]] = set()
    for sentence in re.split(r"[.!?\n]+", content):
        sentence = sentence.strip()
        if not sentence:
            continue
        for pattern in _RELATION_PATTERNS:
            for match in pattern.finditer(sentence):
                src = match.group(1).strip()
                rel = match.group(2).strip().lower()
                tgt = match.group(3).strip()
                key = (canonicalize_entity(src), rel, canonicalize_entity(tgt))
                if key[0] and key[2] and key[0] != key[2] and key not in seen:
                    seen.add(key)
                    triples.append(ExtractedTriple(src, rel, tgt))
    return triples


class GraphService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def _upsert_entity(
        self, workspace_id: uuid.UUID, name: str, entity_type: str = "system"
    ) -> Entity:
        canonical = canonicalize_entity(name)
        existing = (
            await self._session.execute(
                select(Entity).where(
                    Entity.workspace_id == workspace_id,
                    Entity.canonical_key == canonical,
                )
            )
        ).scalar_one_or_none()
        if existing is not None:
            return existing
        entity = Entity(
            workspace_id=workspace_id,
            name=name[:200],
            entity_type=entity_type,
            canonical_key=canonical,
        )
        self._session.add(entity)
        await self._session.flush()
        return entity

    async def index_document_chunks(
        self,
        workspace_id: uuid.UUID,
        document_id: uuid.UUID,
        chunks: list[tuple[uuid.UUID, str]],
    ) -> int:
        """Extract and store entities/edges for all chunks of a document."""
        await self._session.execute(
            delete(EntityEdge).where(
                EntityEdge.workspace_id == workspace_id,
                EntityEdge.document_id == document_id,
            )
        )
        edge_count = 0
        for chunk_id, content in chunks:
            for triple in extract_triples(content):
                src = await self._upsert_entity(
                    workspace_id, triple.source, triple.entity_type
                )
                tgt = await self._upsert_entity(
                    workspace_id, triple.target, triple.entity_type
                )
                self._session.add(
                    EntityEdge(
                        workspace_id=workspace_id,
                        source_entity_id=src.id,
                        relation=triple.relation[:120],
                        target_entity_id=tgt.id,
                        document_id=document_id,
                        chunk_id=chunk_id,
                    )
                )
                edge_count += 1
        await self._session.flush()
        return edge_count

    async def find_2hop_chunks(
        self,
        workspace_id: uuid.UUID,
        query: str,
        allowed_document_ids: list[uuid.UUID] | None = None,
        limit: int = 10,
    ) -> list[ScoredChunk]:
        """1-2 hop recursive SQL CTE graph lookup respecting DocumentGrant RBAC."""
        if allowed_document_ids is not None and len(allowed_document_ids) == 0:
            return []

        # Match workspace entities whose canonical_key appears in the query
        entities = (
            (
                await self._session.execute(
                    select(Entity).where(Entity.workspace_id == workspace_id)
                )
            )
            .scalars()
            .all()
        )
        if not entities:
            return []

        q_norm = canonicalize_entity(query)
        seed_ids: list[uuid.UUID] = []
        for entity in entities:
            key = entity.canonical_key
            if key and (key in q_norm or any(tok == key for tok in q_norm.split())):
                seed_ids.append(entity.id)
        if not seed_ids:
            return []

        # Format UUID binds cleanly for both Postgres and SQLite
        is_sqlite = (
            self._session.bind is not None
            and self._session.bind.dialect.name == "sqlite"
        )

        def _fmt_uuid(val: uuid.UUID) -> object:
            return val.hex if is_sqlite else val

        seed_binds = {f"seed_{i}": _fmt_uuid(eid) for i, eid in enumerate(seed_ids)}
        seed_names = ", ".join(f":{k}" for k in seed_binds)

        doc_clause = ""
        doc_binds: dict[str, object] = {}
        if allowed_document_ids is not None:
            doc_binds = {
                f"doc_{i}": _fmt_uuid(did) for i, did in enumerate(allowed_document_ids)
            }
            doc_names = ", ".join(f":{k}" for k in doc_binds)
            doc_clause = f"AND ee.document_id IN ({doc_names})"

        sql = text(
            f"""
            WITH RECURSIVE graph_walk(entity_id, chunk_id, document_id, hop) AS (
                SELECT ee.target_entity_id, ee.chunk_id, ee.document_id, 1
                FROM entity_edges ee
                JOIN documents d ON d.id = ee.document_id
                WHERE ee.workspace_id = :workspace_id
                  AND d.status = :ready
                  AND ee.source_entity_id IN ({seed_names})
                  {doc_clause}
                UNION
                SELECT ee.source_entity_id, ee.chunk_id, ee.document_id, 1
                FROM entity_edges ee
                JOIN documents d ON d.id = ee.document_id
                WHERE ee.workspace_id = :workspace_id
                  AND d.status = :ready
                  AND ee.target_entity_id IN ({seed_names})
                  {doc_clause}
                UNION
                SELECT ee.target_entity_id, ee.chunk_id, ee.document_id, gw.hop + 1
                FROM graph_walk gw
                JOIN entity_edges ee ON ee.source_entity_id = gw.entity_id
                JOIN documents d ON d.id = ee.document_id
                WHERE gw.hop < 2
                  AND ee.workspace_id = :workspace_id
                  AND d.status = :ready
                  {doc_clause}
            )
            SELECT DISTINCT chunk_id, MIN(hop) AS min_hop
            FROM graph_walk
            GROUP BY chunk_id
            ORDER BY min_hop ASC
            LIMIT :limit
            """
        )
        params: dict[str, object] = {
            "workspace_id": _fmt_uuid(workspace_id),
            "ready": DocumentStatus.READY.value,
            "limit": limit,
            **seed_binds,
            **doc_binds,
        }
        rows = (await self._session.execute(sql, params)).all()
        if not rows:
            return []

        hop_by_chunk: dict[uuid.UUID, int] = {}
        for raw_cid, hop in rows:
            cid = raw_cid if isinstance(raw_cid, uuid.UUID) else uuid.UUID(str(raw_cid))
            hop_by_chunk[cid] = int(hop)

        chunk_rows = (
            await self._session.execute(
                select(DocumentChunk, Document.filename)
                .join(Document, Document.id == DocumentChunk.document_id)
                .where(
                    DocumentChunk.id.in_(list(hop_by_chunk.keys())),
                    DocumentChunk.workspace_id == workspace_id,
                    Document.status == DocumentStatus.READY,
                )
            )
        ).all()

        results: list[ScoredChunk] = []
        for chunk, filename in chunk_rows:
            hop = hop_by_chunk.get(chunk.id, 2)
            # 1-hop gets 0.85, 2-hop gets 0.65 so RRF & reranker rank cleanly
            graph_score = 0.85 if hop == 1 else 0.65
            results.append(
                ScoredChunk(
                    chunk_id=chunk.id,
                    document_id=chunk.document_id,
                    filename=filename,
                    content=chunk.content,
                    page_number=chunk.page_number,
                    heading_path=chunk.heading_path,
                    score=graph_score,
                    parent_content=chunk.parent_content,
                    context_header=chunk.context_header,
                    char_start=chunk.char_start,
                    char_end=chunk.char_end,
                )
            )
        return sorted(results, key=lambda item: item.score, reverse=True)
