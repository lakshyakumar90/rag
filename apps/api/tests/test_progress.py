"""Honest, persistent ingestion progress recorded by the worker."""

import uuid

import pymupdf
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from core.progress import progress_percent
from core.security import hash_password
from models import Document, DocumentStatus, User, Workspace
from workers import ingest

PASSWORD = "StrongPassw0rd!"


class Storage:
    def __init__(self) -> None:
        self.objects: dict[str, tuple[bytes, str]] = {}

    async def upload(self, workspace: str, key: str, data: bytes, mime: str) -> None:
        self.objects[key] = (data, mime)

    async def download(self, workspace: str, key: str) -> bytes:
        return self.objects[key][0]


class Embeddings:
    dimension = 4

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [[1.0, 0.0, 0.0, 0.0] for _ in texts]

    async def embed_query(self, text: str) -> list[float]:
        return [1.0, 0.0, 0.0, 0.0]


def _pdf(pages: int) -> bytes:
    document = pymupdf.open()
    for index in range(pages):
        document.new_page().insert_text(
            (72, 72),
            f"Page {index + 1} describes a unique procedure number {index + 1}.",
        )
    data = document.tobytes()
    document.close()
    return data


async def test_multipage_document_reports_real_progress_and_finishes(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    storage = Storage()
    async with session_factory() as session:
        user = User(
            email=f"progress-{uuid.uuid4()}@example.com",
            password_hash=hash_password(PASSWORD),
        )
        session.add(user)
        await session.flush()
        workspace = Workspace(
            name="Progress", slug=f"progress-{uuid.uuid4().hex[:8]}", created_by=user.id
        )
        session.add(workspace)
        await session.flush()
        data = _pdf(4)
        key = f"{workspace.id}/doc"
        document = Document(
            workspace_id=workspace.id,
            uploaded_by=user.id,
            filename="pages.pdf",
            mime_type="application/pdf",
            size=len(data),
            sha256="b" * 64,
            storage_key=key,
            status=DocumentStatus.PROCESSING,
            ingestion_stage="reading",
            upload_bytes=len(data),
            upload_total=len(data),
            index_version=1,
        )
        session.add(document)
        await session.commit()
        document_id = document.id
    await storage.upload(str(workspace.id), key, data, "application/pdf")

    await ingest.ingest_document(
        {
            "job_try": 1,
            "session_factory": session_factory,
            "storage_client": storage,
            "embedding_provider": Embeddings(),
        },
        str(document_id),
    )

    async with session_factory() as session:
        from repositories import DocumentRepository

        workspace_id = (
            await session.execute(
                select(Document.workspace_id).where(Document.id == document_id)
            )
        ).scalar_one()
        listed = await DocumentRepository(session).list(workspace_id, 0, 10, None)
        assert listed and listed[0].chunks_indexed == listed[0].chunks_total
        assert listed[0].progress_percent == 100.0

        result = await session.execute(
            select(Document).where(Document.id == document_id)
        )
        saved = result.scalar_one()
        assert saved.status == DocumentStatus.READY
        assert saved.pages_total == 4
        assert saved.pages_done == 4
        assert saved.chunks_total > 0
        assert saved.chunks_embedded == saved.chunks_total
        assert saved.chunks_indexed == saved.chunks_total
        assert saved.progress_updated_at is not None
        assert progress_percent(saved) == 100.0
