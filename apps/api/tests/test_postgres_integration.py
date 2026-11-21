"""Optional integration tests against a real PostgreSQL database + pgvector.

These tests exercise behaviour that SQLite cannot reproduce (vector distance,
tsvector full-text search, real FK actions, generated columns). They are skipped
unless a database is available:

* set ``TEST_DATABASE_URL`` to point at an existing PostgreSQL instance, or
* install ``testcontainers[postgres]`` and have Docker running (a
  ``pgvector/pgvector:pg16`` container is started automatically).

See ``docker-compose.test.yml`` for a ready-to-use local database.
"""

import asyncio
import os
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import alembic.command
import alembic.config
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import insert, select, text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

import core.database
from api.v1.dependencies import get_embedding_provider
from core.database import get_session
from core.security import create_access_token
from main import app
from models import (
    AuditLog,
    Conversation,
    Document,
    DocumentChunk,
    DocumentStatus,
    Message,
    MessageFeedback,
    User,
    Workspace,
)
from services.audit import record as record_audit

# All async fixtures and tests share the module loop so the engine's connections
# stay bound to a single event loop.
pytestmark = pytest.mark.asyncio(loop_scope="module")

API = "/api/v1"
PASSWORD = "StrongPassw0rd!"
DIM = 768
ALPHA_INDEX = 0
API_DIR = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class PostgresEnv:
    """Handles for the real database used by this module."""

    engine: AsyncEngine
    factory: async_sessionmaker[AsyncSession]
    url: str
    stop_container: Any = None


class OneHotEmbeddings:
    """Deterministic 768-dim vectors so cosine similarity is predictable."""

    dimension = DIM

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [await self.embed_query(text) for text in texts]

    async def embed_query(self, text: str) -> list[float]:
        vector = [0.0] * DIM
        if "alpha" in text.lower():
            vector[ALPHA_INDEX] = 1.0
        return vector


def _async_url(url: str) -> str:
    """Strip a sync driver suffix and select asyncpg for SQLAlchemy."""
    for suffix in ("+psycopg2", "+psycopg"):
        url = url.replace(f"postgresql{suffix}://", "postgresql://", 1)
    return url.replace("postgresql://", "postgresql+asyncpg://", 1)


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def postgres_env() -> AsyncIterator[PostgresEnv]:
    """Start (or locate) a PostgreSQL database, migrate it, and yield handles."""
    container = None
    raw_url = os.environ.get("TEST_DATABASE_URL")
    if raw_url:
        url = raw_url
    else:
        try:
            from testcontainers.postgres import PostgresContainer
        except ImportError as exc:
            pytest.skip(f"testcontainers[postgres] is required: {exc}")
        try:
            container = PostgresContainer("pgvector/pgvector:pg16", driver="psycopg")
            container.start()
            url = container.get_connection_url()
        except Exception as exc:
            if container is not None:
                try:
                    container.stop()
                except Exception:
                    pass
            pytest.skip(f"Docker/PostgreSQL unavailable: {exc}")

    url = _async_url(url)
    try:
        engine = create_async_engine(url, pool_pre_ping=True)
    except ImportError as exc:
        pytest.skip(f"asyncpg is required for PostgreSQL integration tests: {exc}")
    factory = async_sessionmaker(engine, expire_on_commit=False)

    # alembic/env.py imports `engine` from core.database when upgrade() runs.
    original_engine = core.database.engine
    config = alembic.config.Config(str(API_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(API_DIR / "alembic"))
    try:
        core.database.engine = engine
        # env.py uses asyncio.run(), so run it off the active loop thread.
        await asyncio.to_thread(alembic.command.upgrade, config, "head")
    finally:
        core.database.engine = original_engine

    try:
        yield PostgresEnv(
            engine=engine, factory=factory, url=url, stop_container=container
        )
    finally:
        await engine.dispose()
        if container is not None:
            container.stop()


@pytest_asyncio.fixture(loop_scope="module")
async def client(postgres_env: PostgresEnv) -> AsyncIterator[AsyncClient]:
    """ASGI client backed by the PostgreSQL session factory (not SQLite)."""
    factory = postgres_env.factory

    async def override_get_session() -> AsyncIterator[AsyncSession]:
        async with factory() as session:
            yield session

    previous = app.dependency_overrides.get(get_session)
    app.dependency_overrides[get_session] = override_get_session
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="https://testserver"
        ) as async_client:
            yield async_client
    finally:
        if previous is None:
            app.dependency_overrides.pop(get_session, None)
        else:
            app.dependency_overrides[get_session] = previous


async def _register(client: AsyncClient, email: str) -> dict[str, str]:
    """Create a user via the API and mint an access token from its returned id."""
    response = await client.post(
        f"{API}/auth/register", json={"email": email, "password": PASSWORD}
    )
    assert response.status_code == 201, response.text
    token = create_access_token(uuid.UUID(response.json()["id"]))
    return {"Authorization": f"Bearer {token}"}


async def _workspace(client: AsyncClient, headers: dict[str, str], slug: str) -> str:
    response = await client.post(
        f"{API}/workspaces", headers=headers, json={"name": slug, "slug": slug}
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


async def _seed_document(
    factory: async_sessionmaker[AsyncSession],
    workspace_id: uuid.UUID,
    uploader_id: uuid.UUID,
    filename: str,
    content: str,
    term_index: int,
) -> uuid.UUID:
    """Insert a ready document and a chunk with a real one-hot pgvector value.

    ``document_chunks.search_vector`` is a generated column, so it is omitted
    from the insert; PostgreSQL derives it from ``content``.
    """
    embedding = [0.0] * DIM
    embedding[term_index] = 1.0
    document_id = uuid.uuid4()
    async with factory() as session:
        await session.execute(
            insert(Document).values(
                id=document_id,
                workspace_id=workspace_id,
                uploaded_by=uploader_id,
                filename=filename,
                mime_type="text/plain",
                size=len(content),
                sha256=uuid.uuid4().hex + uuid.uuid4().hex,
                storage_key=f"{workspace_id}/{uuid.uuid4()}",
                status=DocumentStatus.READY,
                embedding_dim=DIM,
            )
        )
        await session.execute(
            insert(DocumentChunk).values(
                document_id=document_id,
                workspace_id=workspace_id,
                chunk_index=0,
                content=content,
                embedding=embedding,
                token_count=len(content.split()),
            )
        )
        await session.commit()
    return document_id


async def test_migrations_create_expected_schema(postgres_env: PostgresEnv) -> None:
    """Alembic must build the full PostgreSQL schema, including pgvector."""
    async with postgres_env.factory() as session:
        tables = {
            row[0]
            for row in (
                await session.execute(
                    text(
                        "SELECT table_name FROM information_schema.tables "
                        "WHERE table_schema = 'public'"
                    )
                )
            ).all()
        }
        extensions = {
            row[0]
            for row in (
                await session.execute(text("SELECT extname FROM pg_extension"))
            ).all()
        }
        chunk_columns = {
            row[0]
            for row in (
                await session.execute(
                    text(
                        "SELECT column_name FROM information_schema.columns "
                        "WHERE table_name = 'document_chunks'"
                    )
                )
            ).all()
        }

    assert {"message_feedback", "audit_logs", "documents", "messages"} <= tables
    assert "vector" in extensions
    assert "search_vector" in chunk_columns


async def test_pgvector_and_fulltext_search_are_workspace_scoped(
    client: AsyncClient, postgres_env: PostgresEnv
) -> None:
    """Real vector/tsvector search must never cross a workspace boundary."""
    headers_a = await _register(client, "pg-a@example.com")
    headers_b = await _register(client, "pg-b@example.com")
    wid_a = await _workspace(client, headers_a, "pg-workspace-a")
    wid_b = await _workspace(client, headers_b, "pg-workspace-b")

    async with postgres_env.factory() as session:
        user_ids: dict[str, uuid.UUID] = {
            email: user_id
            for user_id, email in (
                await session.execute(
                    select(User.id, User.email).where(
                        User.email.in_(["pg-a@example.com", "pg-b@example.com"])
                    )
                )
            ).all()
        }

    content = "alpha payload"
    doc_a = await _seed_document(
        postgres_env.factory,
        uuid.UUID(wid_a),
        user_ids["pg-a@example.com"],
        "a.txt",
        content,
        ALPHA_INDEX,
    )
    await _seed_document(
        postgres_env.factory,
        uuid.UUID(wid_b),
        user_ids["pg-b@example.com"],
        "b.txt",
        content,
        ALPHA_INDEX,
    )

    app.dependency_overrides[get_embedding_provider] = lambda: OneHotEmbeddings()
    try:
        response = await client.post(
            f"{API}/workspaces/{wid_a}/search",
            headers=headers_a,
            json={"query": "alpha"},
        )
    finally:
        app.dependency_overrides.pop(get_embedding_provider, None)

    assert response.status_code == 200, response.text
    items = response.json()["items"]
    assert items  # both vector and keyword indexes found the row
    assert {item["document_id"] for item in items} == {str(doc_a)}
    assert all(item["filename"] == "a.txt" for item in items)


async def test_audit_foreign_keys_set_null_after_account_deletion(
    client: AsyncClient, postgres_env: PostgresEnv
) -> None:
    """Deleting a user/workspace nulls audit FKs but keeps the actor email."""
    headers = await _register(client, "pg-audit@example.com")
    wid = await _workspace(client, headers, "pg-audit")

    async with postgres_env.factory() as session:
        user = (
            await session.execute(
                select(User).where(User.email == "pg-audit@example.com")
            )
        ).scalar_one()
        workspace = (
            await session.execute(
                select(Workspace).where(Workspace.id == uuid.UUID(wid))
            )
        ).scalar_one()
        entry = await record_audit(
            session, user, "account.deleted", workspace_id=workspace.id
        )
        audit_id = entry.id
        # delete_account() removes workspaces before the user; mirror that here
        # so the real SET NULL actions are exercised by the database.
        await session.delete(workspace)
        await session.flush()
        await session.delete(user)
        await session.commit()

    async with postgres_env.factory() as session:
        saved = (
            await session.execute(select(AuditLog).where(AuditLog.id == audit_id))
        ).scalar_one()
        assert saved.user_id is None
        assert saved.workspace_id is None
        assert saved.actor_email == "pg-audit@example.com"


async def test_feedback_unique_and_cascade(
    client: AsyncClient, postgres_env: PostgresEnv
) -> None:
    """Feedback upserts to one row and cascades when its conversation is gone."""
    headers = await _register(client, "pg-feedback@example.com")
    wid = await _workspace(client, headers, "pg-feedback")

    async with postgres_env.factory() as session:
        user_id = (
            await session.execute(
                select(User.id).where(User.email == "pg-feedback@example.com")
            )
        ).scalar_one()
        conversation = Conversation(
            workspace_id=uuid.UUID(wid), user_id=user_id, title="Chat"
        )
        session.add(conversation)
        await session.flush()
        message = Message(
            conversation_id=conversation.id,
            sequence=1,
            role="assistant",
            content="Grounded answer.",
        )
        session.add(message)
        await session.commit()
        conversation_id = conversation.id
        message_id = message.id

    url = f"{API}/workspaces/{wid}/messages/{message_id}/feedback"
    for vote in ("up", "down"):
        response = await client.post(url, headers=headers, json={"vote": vote})
        assert response.status_code == 200, response.text
        assert response.json()["vote"] == vote

    async with postgres_env.factory() as session:
        rows = (
            (
                await session.execute(
                    select(MessageFeedback).where(
                        MessageFeedback.message_id == message_id
                    )
                )
            )
            .scalars()
            .all()
        )
        assert len(rows) == 1
        assert rows[0].vote == "down"

    deleted = await client.delete(
        f"{API}/workspaces/{wid}/conversations/{conversation_id}", headers=headers
    )
    assert deleted.status_code == 204, deleted.text

    async with postgres_env.factory() as session:
        remaining = (
            (
                await session.execute(
                    select(MessageFeedback).where(
                        MessageFeedback.message_id == message_id
                    )
                )
            )
            .scalars()
            .all()
        )
        assert remaining == []
