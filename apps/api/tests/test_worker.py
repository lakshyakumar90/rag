"""Tests for the ARQ ingestion task and upload enqueueing."""

import asyncio
import uuid
from datetime import timedelta

import pytest
from arq import Retry
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from core.config import get_settings
from core.security import hash_password
from models import Document, DocumentStatus, User, Workspace
from workers import ingest
from workers.settings import WorkerSettings

PASSWORD = "StrongPassw0rd!"


async def _document(
    factory: async_sessionmaker[AsyncSession], status: DocumentStatus
) -> uuid.UUID:
    async with factory() as session:
        user = User(email="uploader@example.com", password_hash=hash_password(PASSWORD))
        session.add(user)
        await session.flush()
        workspace = Workspace(name="Acme", slug="acme", created_by=user.id)
        session.add(workspace)
        await session.flush()
        document = Document(
            workspace_id=workspace.id,
            uploaded_by=user.id,
            filename="doc.txt",
            mime_type="text/plain",
            size=5,
            sha256="a" * 64,
            storage_key=f"{workspace.id}/key",
            status=status,
        )
        session.add(document)
        await session.commit()
        return document.id


async def _status(
    factory: async_sessionmaker[AsyncSession], document_id: uuid.UUID
) -> tuple[DocumentStatus, str | None]:
    async with factory() as session:
        document = await session.get(Document, document_id)
        assert document is not None
        return document.status, document.error


async def test_upload_enqueues_ingest_job(client: AsyncClient, fake_job_queue) -> None:
    registered = await client.post(
        "/api/v1/auth/register",
        json={"email": "owner@example.com", "password": PASSWORD},
    )
    assert registered.status_code == 201
    login = await client.post(
        "/api/v1/auth/login", json={"email": "owner@example.com", "password": PASSWORD}
    )
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    created = await client.post(
        "/api/v1/workspaces", headers=headers, json={"name": "Acme", "slug": "acme"}
    )
    wid = created.json()["id"]

    uploaded = await client.post(
        f"/api/v1/workspaces/{wid}/documents",
        headers=headers,
        files={"file": ("doc.txt", b"hello", "text/plain")},
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
        files={"file": ("doc.txt", b"hello", "text/plain")},
    )
    assert uploaded.status_code == 201
    assert uploaded.json()["status"] == "pending"


async def test_ingest_marks_document_ready(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    document_id = await _document(session_factory, DocumentStatus.PENDING)

    await ingest.ingest_document(
        {"job_try": 1, "session_factory": session_factory}, str(document_id)
    )

    assert (await _status(session_factory, document_id))[0] is DocumentStatus.READY


async def test_ingest_retries_with_exponential_backoff(
    session_factory: async_sessionmaker[AsyncSession], monkeypatch
) -> None:
    async def _fails(document_id, factory):
        raise RuntimeError("transient")

    monkeypatch.setattr(ingest, "_process", _fails)
    document_id = await _document(session_factory, DocumentStatus.PENDING)
    ctx = {"job_try": 1, "session_factory": session_factory}

    with pytest.raises(Retry) as retry:
        await ingest.ingest_document(ctx, str(document_id))
    base = get_settings().ingest_retry_backoff_seconds
    assert retry.value.defer_score == int(base * 1000)
    # A retryable failure must not mark the row failed before the last try.
    assert (await _status(session_factory, document_id))[1] is None

    with pytest.raises(Retry) as second:
        await ingest.ingest_document(
            {"job_try": 2, "session_factory": session_factory}, str(document_id)
        )
    assert second.value.defer_score == int(base * 2 * 1000)


async def test_ingest_records_failure_on_last_attempt(
    session_factory: async_sessionmaker[AsyncSession], monkeypatch
) -> None:
    async def _fails(document_id, factory):
        raise RuntimeError("permanent failure")

    monkeypatch.setattr(ingest, "_process", _fails)
    document_id = await _document(session_factory, DocumentStatus.PENDING)

    with pytest.raises(RuntimeError, match="permanent failure"):
        await ingest.ingest_document(
            {
                "job_try": get_settings().ingest_max_tries,
                "session_factory": session_factory,
            },
            str(document_id),
        )

    status, error = await _status(session_factory, document_id)
    assert status is DocumentStatus.FAILED
    assert error is not None and "permanent failure" in error


async def test_ingest_timeout_recorded_as_failure(
    session_factory: async_sessionmaker[AsyncSession], monkeypatch
) -> None:
    async def _slow(document_id, factory):
        await asyncio.sleep(5)

    monkeypatch.setattr(ingest, "_process", _slow)
    document_id = await _document(session_factory, DocumentStatus.PENDING)
    monkeypatch.setattr(get_settings(), "ingest_job_timeout_seconds", 0.05)

    with pytest.raises(asyncio.TimeoutError):
        await ingest.ingest_document(
            {
                "job_try": get_settings().ingest_max_tries,
                "session_factory": session_factory,
            },
            str(document_id),
        )

    status, error = await _status(session_factory, document_id)
    assert status is DocumentStatus.FAILED
    assert error is not None and "Timeout" in error


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
