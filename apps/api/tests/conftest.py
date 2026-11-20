"""Test fixtures: real SQLite database, in-memory fake Redis, ASGI client."""

from collections.abc import AsyncIterator

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from core.database import get_session
from core.redis import get_redis_client
from main import app
from models import Base


class FakeRedis:
    """Minimal stand-in for the two Redis commands the rate limiter uses."""

    def __init__(self) -> None:
        self.values: dict[str, int] = {}
        self.ttls: dict[str, int] = {}

    async def eval(self, _script: str, numkeys: int, *args: object) -> list[int]:
        keys = [str(arg) for arg in args[:numkeys]]
        window = int(str(args[numkeys]))
        result: list[int] = []
        for key in keys:
            count = self.values.get(key, 0) + 1
            self.values[key] = count
            if count == 1:
                self.ttls[key] = window
            result.extend((count, self.ttls.get(key, -1)))
        return result

    async def delete(self, *keys: object) -> None:
        for key in keys:
            self.values.pop(str(key), None)
            self.ttls.pop(str(key), None)

    async def aclose(self) -> None:
        return None


@pytest_asyncio.fixture
async def fake_redis() -> FakeRedis:
    return FakeRedis()


@pytest_asyncio.fixture
async def session_factory() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        yield factory
    finally:
        await engine.dispose()


@pytest_asyncio.fixture
async def client(
    session_factory: async_sessionmaker[AsyncSession], fake_redis: FakeRedis
) -> AsyncIterator[AsyncClient]:
    async def override_get_session() -> AsyncIterator[AsyncSession]:
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_session] = override_get_session
    app.dependency_overrides[get_redis_client] = lambda: fake_redis
    try:
        # https so Secure cookies are stored and sent back by httpx's jar.
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="https://testserver"
        ) as async_client:
            yield async_client
    finally:
        app.dependency_overrides.clear()
