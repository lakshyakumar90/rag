"""Tests for the ARQ ingestion task, extraction and upload enqueueing."""

import asyncio
import io
import uuid
from datetime import timedelta

import pymupdf
import pytest
from arq import Retry
from docx import Document as DocxDocument
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from core.config import get_settings
from core.security import hash_password
from models import Document, DocumentChunk, DocumentStatus, User, Workspace
from workers import ingest
from workers.extraction import EmptyDocumentError, extract
from workers.settings import WorkerSettings

PASSWORD = "StrongPassw0rd!"


def _pdf(pages: list[str]) -> bytes:
    document = pymupdf.open()
    for text in pages:
        document.new_page().insert_text((72, 72), text)
    data = document.tobytes()
    document.close()
    return data


def _docx(text: str) -> bytes:
    document = DocxDocument()
    document.add_paragraph(text)
    buffer = io.BytesIO()
    document.save(buffer)
    return buffer.getvalue()


async def _document(
    factory: async_sessionmaker[AsyncSession],
    status: DocumentStatus = DocumentStatus.PENDING,
    *,
    mime_type: str = "text/plain",
    storage=None,
    data: bytes = b"a sufficiently long plain text document",
) -> uuid.UUID:
    async with factory() as session:
        user = User(
            email=f"uploader-{uuid.uuid4()}@example.com",
            password_hash=hash_password(PASSWORD),
        )
        session.add(user)
        await session.flush()
        workspace = Workspace(
            name="Acme", slug=f"acme-{uuid.uuid4().hex[:8]}", created_by=user.id
        )
        session.add(workspace)
        await session.flush()
        key = f"{workspace.id}/key"
        document = Document(
            workspace_id=workspace.id,
            uploaded_by=user.id,
            filename="doc.txt",
            mime_type=mime_type,
            size=len(data),
            sha256="a" * 64,
            storage_key=key,
            status=status,
        )
        session.add(document)
        await session.commit()
        document_id = document.id
    if storage is not None:
        await storage.upload(str(workspace.id), key, data, mime_type)
    return document_id


async def _status(
    factory: async_sessionmaker[AsyncSession], document_id: uuid.UUID
) -> tuple[DocumentStatus, str | None]:
    async with factory() as session:
        document = await session.get(Document, document_id)
        assert document is not None
        return document.status, document.error


def _ctx(factory, storage, embeddings, job_try: int = 1) -> dict:
    return {
        "job_try": job_try,
        "session_factory": factory,
        "storage_client": storage,
        "embedding_provider": embeddings,
    }


async def test_upload_enqueues_ingest_job(client: AsyncClient, fake_job_queue) -> None:
    await client.post(
        "/api/v1/auth/register",
        json={"email": "owner@example.com", "password": PASSWORD},
    )
    login = await client.post(
        "/api/v1/auth/login", json={"email": "owner@example.com", "password": PASSWORD}
    )
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    wid = (
        await client.post(
            "/api/v1/workspaces", headers=headers, json={"name": "Acme", "slug": "acme"}
        )
    ).json()["id"]

    uploaded = await client.post(
        f"/api/v1/workspaces/{wid}/documents",
        headers=headers,
        files={"file": ("doc.txt", b"hello world document", "text/plain")},
    )
    assert uploaded.status_code == 201
    assert uploaded.json()["status"] == "pending"
    assert len(fake_job_queue.jobs) == 1
    assert str(fake_job_queue.jobs[0]) == uploaded.json()["id"]


async def test_queue_outage_does_not_fail_upload(
    client: AsyncClient, fake_job_queue
) -> None:
    fake_job_queue.fail = True
    await client.post(
        "/api/v1/auth/register",
        json={"email": "owner@example.com", "password": PASSWORD},
    )
    login = await client.post(
        "/api/v1/auth/login", json={"email": "owner@example.com", "password": PASSWORD}
    )
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    wid = (
        await client.post(
            "/api/v1/workspaces", headers=headers, json={"name": "Acme", "slug": "acme"}
        )
    ).json()["id"]
    uploaded = await client.post(
        f"/api/v1/workspaces/{wid}/documents",
        headers=headers,
        files={"file": ("doc.txt", b"hello world document", "text/plain")},
    )
    assert uploaded.status_code == 201
    assert uploaded.json()["status"] == "pending"


async def test_ingest_stores_chunks_from_text(
    session_factory: async_sessionmaker[AsyncSession],
    fake_storage,
    fake_embedding_provider,
) -> None:
    document_id = await _document(
        session_factory,
        storage=fake_storage,
        data=b"First paragraph here.\n\nSecond paragraph follows.",
    )
    await ingest.ingest_document(
        _ctx(session_factory, fake_storage, fake_embedding_provider), str(document_id)
    )

    assert (await _status(session_factory, document_id))[0] is DocumentStatus.READY
    async with session_factory() as session:
        chunks = (
            (
                await session.execute(
                    select(DocumentChunk)
                    .where(DocumentChunk.document_id == document_id)
                    .order_by(DocumentChunk.chunk_index)
                )
            )
            .scalars()
            .all()
        )
        assert len(chunks) >= 1
        assert all(chunk.page_number is None for chunk in chunks)
        assert "First paragraph here" in chunks[0].content
        assert all(
            len(chunk.embedding) == fake_embedding_provider.dimension
            for chunk in chunks
        )
        assert fake_embedding_provider.calls == [
            ["First paragraph here. Second paragraph follows."]
        ]


async def test_ingest_persists_heading_path_and_token_count(
    session_factory: async_sessionmaker[AsyncSession],
    fake_storage,
    fake_embedding_provider,
) -> None:
    markdown = (
        b"# Guide\n\nIntroduction with enough text to keep.\n\n"
        b"## Install\n\nInstallation steps with enough text to keep."
    )
    document_id = await _document(
        session_factory,
        storage=fake_storage,
        mime_type="text/markdown",
        data=markdown,
    )
    await ingest.ingest_document(
        _ctx(session_factory, fake_storage, fake_embedding_provider), str(document_id)
    )

    async with session_factory() as session:
        chunks = (
            (
                await session.execute(
                    select(DocumentChunk)
                    .where(DocumentChunk.document_id == document_id)
                    .order_by(DocumentChunk.chunk_index)
                )
            )
            .scalars()
            .all()
        )
        assert chunks
        assert [chunk.chunk_index for chunk in chunks] == list(range(len(chunks)))
        assert all(chunk.workspace_id == chunks[0].workspace_id for chunk in chunks)
        assert all(chunk.token_count > 0 for chunk in chunks)
        assert {tuple(chunk.heading_path or ()) for chunk in chunks} == {
            ("Guide",),
            ("Guide", "Install"),
        }
        assert all(chunk.page_number is None for chunk in chunks)


async def test_ingest_retries_with_exponential_backoff(
    session_factory: async_sessionmaker[AsyncSession],
    fake_storage,
    fake_embedding_provider,
    monkeypatch,
) -> None:
    async def _fails(document_id, factory, storage, embeddings):
        raise RuntimeError("transient")

    monkeypatch.setattr(ingest, "_process", _fails)
    document_id = await _document(session_factory, storage=fake_storage)

    with pytest.raises(Retry) as retry:
        await ingest.ingest_document(
            _ctx(session_factory, fake_storage, fake_embedding_provider, 1),
            str(document_id),
        )
    base = get_settings().ingest_retry_backoff_seconds
    assert retry.value.defer_score == int(base * 1000)
    assert (await _status(session_factory, document_id))[1] is None

    with pytest.raises(Retry) as second:
        await ingest.ingest_document(
            _ctx(session_factory, fake_storage, fake_embedding_provider, 2),
            str(document_id),
        )
    assert second.value.defer_score == int(base * 2 * 1000)


async def test_ingest_records_failure_on_last_attempt(
    session_factory: async_sessionmaker[AsyncSession],
    fake_storage,
    fake_embedding_provider,
    monkeypatch,
) -> None:
    async def _fails(document_id, factory, storage, embeddings):
        raise RuntimeError("permanent failure")

    monkeypatch.setattr(ingest, "_process", _fails)
    document_id = await _document(session_factory, storage=fake_storage)

    with pytest.raises(RuntimeError, match="permanent failure"):
        await ingest.ingest_document(
            _ctx(
                session_factory,
                fake_storage,
                fake_embedding_provider,
                get_settings().ingest_max_tries,
            ),
            str(document_id),
        )

    status, error = await _status(session_factory, document_id)
    assert status is DocumentStatus.FAILED
    assert error is not None and "permanent failure" in error


async def test_ingest_timeout_recorded_as_failure(
    session_factory: async_sessionmaker[AsyncSession],
    fake_storage,
    fake_embedding_provider,
    monkeypatch,
) -> None:
    async def _slow(document_id, factory, storage, embeddings):
        await asyncio.sleep(5)

    monkeypatch.setattr(ingest, "_process", _slow)
    document_id = await _document(session_factory, storage=fake_storage)
    monkeypatch.setattr(get_settings(), "ingest_job_timeout_seconds", 0.05)

    with pytest.raises(asyncio.TimeoutError):
        await ingest.ingest_document(
            _ctx(
                session_factory,
                fake_storage,
                fake_embedding_provider,
                get_settings().ingest_max_tries,
            ),
            str(document_id),
        )

    status, error = await _status(session_factory, document_id)
    assert status is DocumentStatus.FAILED
    assert error is not None and "Timeout" in error


def test_extract_pdf_keeps_page_numbers_and_cleans_text() -> None:
    data = _pdf(
        [
            "Acme Confidential\nThe inter-\nnational project starts here.",
            "Acme Confidential\nSecond page has its own content.",
            "Acme Confidential\nThird page finishes the report.",
        ]
    )
    result = extract(data, "application/pdf")
    assert result.page_count == 3
    assert [page.page_number for page in result.pages] == [1, 2, 3]
    joined = "\n".join(page.text for page in result.pages)
    assert "international" in joined  # hyphenation repaired
    assert "Acme Confidential" not in joined  # repeated header stripped
    assert "starts here" in joined


def test_extract_docx_txt_and_markdown() -> None:
    docx = extract(
        _docx("A(docx) paragraph with enough text to keep."),
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )
    assert docx.page_count is None
    assert "enough text" in docx.pages[0].text
    assert docx.pages[0].page_number is None

    txt = extract(b"plain text with enough characters to pass", "text/plain")
    md = extract(b"# Heading\n\nmarkdown body with enough characters", "text/markdown")
    assert "plain text" in txt.pages[0].text
    assert "markdown body" in md.pages[0].text


def test_empty_and_scanned_pdfs_are_rejected() -> None:
    empty = _pdf([""])
    with pytest.raises(EmptyDocumentError, match="OCR is not available"):
        extract(empty, "application/pdf")

    # A page with graphics but no text is treated the same as a scan.
    document = pymupdf.open()
    page = document.new_page()
    page.draw_rect(pymupdf.Rect(10, 10, 200, 200))
    scanned = document.tobytes()
    document.close()
    with pytest.raises(EmptyDocumentError, match="No selectable text"):
        extract(scanned, "application/pdf")


async def test_empty_pdf_fails_immediately_without_retry(
    session_factory: async_sessionmaker[AsyncSession],
    fake_storage,
    fake_embedding_provider,
) -> None:
    document_id = await _document(
        session_factory,
        storage=fake_storage,
        mime_type="application/pdf",
        data=_pdf([""]),
    )
    with pytest.raises(EmptyDocumentError):
        await ingest.ingest_document(
            _ctx(session_factory, fake_storage, fake_embedding_provider, 1),
            str(document_id),
        )

    status, error = await _status(session_factory, document_id)
    assert status is DocumentStatus.FAILED
    assert error is not None and "OCR is not available" in error


def test_worker_settings_configured() -> None:
    function = WorkerSettings.functions[0]
    assert function.name == "ingest_document"
    assert function.max_tries == get_settings().ingest_max_tries
    assert (
        function.timeout_s
        == timedelta(
            seconds=get_settings().ingest_job_timeout_seconds + 10
        ).total_seconds()
    )
    assert WorkerSettings.retry_jobs is True
    assert "session_factory" in WorkerSettings.ctx
    assert "storage_client" in WorkerSettings.ctx
    assert "embedding_provider" in WorkerSettings.ctx
