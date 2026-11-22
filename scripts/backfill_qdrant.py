#!/usr/bin/env python3
"""Resumable PostgreSQL -> Qdrant embedding backfill.

    uv run python scripts/backfill_qdrant.py            # write missing points
    uv run python scripts/backfill_qdrant.py --verify   # counts + sample search
    uv run python scripts/backfill_qdrant.py --rollback # drop the collection

The script only copies embeddings whose model, dimension and distance match the
active profile. It never modifies PostgreSQL documents or chunks. A checkpoint
table records what was written per (document, profile), so reruns skip finished
documents and an interrupted document is safely re-upserted from scratch.
Switch reads with ``QDRANT_ENABLED=true`` only after ``--verify`` passes; the
rollback path is setting it back to ``false`` (pgvector stays intact).
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import uuid
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "apps" / "api"))

from sqlalchemy import and_, func, or_, select  # noqa: E402

from core.config import get_settings  # noqa: E402
from core.database import SessionFactory  # noqa: E402
from models import Document, DocumentChunk, DocumentStatus, QdrantSyncState  # noqa: E402
from providers.qdrant import (  # noqa: E402
    QdrantClient,
    collection_name,
    document_filter,
    profile_filter,
)
from services.qdrant_index import QdrantIndexService  # noqa: E402


@dataclass(frozen=True)
class _BackfillChunk:
    id: uuid.UUID
    document_id: uuid.UUID
    chunk_index: int
    page_number: int | None
    embedding: list[float] | None


async def _ready_documents(session, profile: str, limit: int | None, settings):
    # Pre-v2 rows have no profile stored. Treat rows whose model/dimension match
    # the shipped default as part of that profile (no re-embedding needed).
    compatible = and_(
        Document.embedding_profile.is_(None),
        or_(
            Document.embedding_model == settings.ollama_embedding_model,
            Document.embedding_model.is_(None),
        ),
        or_(
            Document.embedding_dim == settings.embedding_dim,
            Document.embedding_dim.is_(None),
        ),
    )
    statement = (
        select(Document)
        .where(
            Document.status == DocumentStatus.READY,
            or_(Document.embedding_profile == profile, compatible),
        )
        .order_by(Document.created_at)
    )
    if limit:
        statement = statement.limit(limit)
    return (await session.execute(statement)).scalars().all()


async def _document_chunks(session, document_id: uuid.UUID) -> list[_BackfillChunk]:
    rows = (
        (
            await session.execute(
                select(DocumentChunk)
                .where(
                    DocumentChunk.document_id == document_id,
                    DocumentChunk.embedding.is_not(None),
                )
                .order_by(DocumentChunk.chunk_index)
            )
        )
        .scalars()
        .all()
    )
    return [
        _BackfillChunk(
            id=row.id,
            document_id=row.document_id,
            chunk_index=row.chunk_index,
            page_number=row.page_number,
            embedding=list(row.embedding) if row.embedding is not None else None,
        )
        for row in rows
    ]


async def _pg_count(session, document_id: uuid.UUID) -> int:
    return int(
        (
            await session.execute(
                select(func.count())
                .select_from(DocumentChunk)
                .where(
                    DocumentChunk.document_id == document_id,
                    DocumentChunk.embedding.is_not(None),
                )
            )
        ).scalar_one()
    )


async def run(args: argparse.Namespace) -> int:
    settings = get_settings()
    profile = args.profile or settings.embedding_profile
    client = QdrantClient()
    # The backfill runs *before* QDRANT_ENABLED is switched on, so the indexer
    # must not consult that read-path flag.
    indexer_settings = settings.model_copy(update={"qdrant_enabled": True})
    indexer = QdrantIndexService(client, SessionFactory, indexer_settings)
    name = collection_name(profile, settings.qdrant_collection_prefix)

    try:
        await client.health()
        if args.rollback:
            info = await client.get_collection(name)
            if info is None:
                print(f"collection {name} does not exist; nothing to roll back")
                return 0
            await client.delete_collection(name)
            print(f"dropped collection {name}; set QDRANT_ENABLED=false if needed")
            return 0

        await indexer.prepare(profile, settings.embedding_dim)
        async with SessionFactory() as session:
            documents = await _ready_documents(session, profile, args.limit, settings)
        total_documents = len(documents)
        skipped = written_documents = 0

        for number, document in enumerate(documents, start=1):
            async with SessionFactory() as session:
                chunks = await _document_chunks(session, document.id)
                state = (
                    await session.execute(
                        select(QdrantSyncState).where(
                            QdrantSyncState.document_id == document.id,
                            QdrantSyncState.embedding_profile == profile,
                        )
                    )
                ).scalar_one_or_none()
            if (
                not args.force
                and state is not None
                and state.status == "completed"
                and state.index_version == document.index_version
                and state.chunks_written == len(chunks)
            ):
                skipped += 1
                continue

            if args.dry_run or args.verify:
                if not args.verify:
                    print(f"[dry-run] {document.filename}: {len(chunks)} chunks")
                continue
            written = await indexer.sync_chunks(
                document.workspace_id,
                document.id,
                chunks,
                profile,
                document.index_version,
                settings.embedding_dim,
            )
            if written != len(chunks):
                raise RuntimeError(
                    f"{document.filename}: wrote {written} of {len(chunks)} chunks"
                )
            written_documents += 1
            print(
                f"[{number}/{total_documents}] {document.filename}: "
                f"{len(chunks)} chunks written"
            )

        if args.dry_run:
            return 0

        # Verification: counts agree with PostgreSQL and sample vectors find
        # their own chunk through filtered Qdrant search.
        failures: list[str] = []
        for document in documents[: args.verify_limit]:
            async with SessionFactory() as session:
                chunks = await _document_chunks(session, document.id)
                expected = await _pg_count(session, document.id)
            actual = await client.count(
                name,
                must=[document_filter(document.id), profile_filter(profile)],
            )
            if actual != expected:
                failures.append(
                    f"{document.filename}: qdrant={actual} postgres={expected}"
                )
            for chunk in chunks[: args.sample_size]:
                if chunk.embedding is None:
                    continue
                hits = await client.search(
                    name,
                    chunk.embedding,
                    1,
                    must=[document_filter(document.id), profile_filter(profile)],
                )
                if not hits or str(hits[0]["id"]) != str(chunk.id):
                    failures.append(
                        f"{document.filename}: sample chunk {chunk.id} not found"
                    )

        if not args.verify:
            print(
                f"done: {written_documents} written, {skipped} already current, "
                f"{total_documents} total"
            )
        if failures:
            print("VERIFICATION FAILED:")
            for failure in failures:
                print(f"  - {failure}")
            return 1
        print(f"VERIFICATION OK: counts and sample retrieval match collection {name}")
        return 0
    finally:
        await client.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--profile", help="embedding profile id (default from settings)"
    )
    parser.add_argument(
        "--limit", type=int, default=None, help="max documents to process"
    )
    parser.add_argument("--batch-size", type=int, default=None)
    parser.add_argument(
        "--force", action="store_true", help="rebuild finished documents"
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--verify", action="store_true", help="run verification after write"
    )
    parser.add_argument("--verify-limit", type=int, default=10)
    parser.add_argument("--sample-size", type=int, default=2)
    parser.add_argument(
        "--rollback", action="store_true", help="drop the Qdrant collection"
    )
    args = parser.parse_args()
    if args.batch_size:
        get_settings().qdrant_batch_size = args.batch_size
    return asyncio.run(run(args))


if __name__ == "__main__":
    raise SystemExit(main())
