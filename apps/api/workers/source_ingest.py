"""ARQ job: fetch an external source, then run the normal ingestion pipeline."""

import hashlib
import uuid

from arq import Retry
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from core.config import get_settings
from models import Document, DocumentStatus
from providers.storage import StorageClient
from services.sources import (
    SourceFetchError,
    fetch_github,
    fetch_url,
)
from workers import ingest


async def ingest_source(ctx: dict, document_id: str) -> None:
    settings = get_settings()
    factory: async_sessionmaker[AsyncSession] = ctx["session_factory"]
    storage: StorageClient = ctx["storage_client"]
    doc_id = uuid.UUID(document_id)
    attempt = int(ctx.get("job_try", 1))

    async with factory() as session:
        document = await session.get(Document, doc_id)
        if document is None:
            return
        workspace_id = document.workspace_id
        source_type = document.source_type
        metadata = document.source_metadata or {}
        key = document.storage_key
        try:
            if source_type == "url":
                fetched = await fetch_url(document.source_url or "")
            elif source_type == "github":
                fetched = await fetch_github(
                    str(metadata.get("owner", "")),
                    str(metadata.get("repo", "")),
                    metadata.get("ref"),
                )
            else:
                return
        except SourceFetchError as exc:
            if attempt >= settings.ingest_max_tries:
                document.status = DocumentStatus.FAILED
                document.error = str(exc)[:2000]
                await session.commit()
                return
            raise Retry(defer=settings.ingest_retry_backoff_seconds * attempt) from exc

        data = fetched.text.encode("utf-8")
        document.size = len(data)
        document.sha256 = hashlib.sha256(data).hexdigest()
        document.mime_type = fetched.mime_type
        document.source_metadata = {**metadata, **fetched.metadata}
        await session.commit()

    await storage.upload(str(workspace_id), key, data, fetched.mime_type)
    # The shared pipeline owns chunking, embedding, Qdrant writes and progress.
    await ingest.ingest_document(ctx, document_id)
