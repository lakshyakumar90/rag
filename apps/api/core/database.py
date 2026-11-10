import asyncio
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from core.config import get_settings

# psycopg3's async mode needs a selector-based event loop (it relies on
# add_reader), which Windows' default ProactorEventLoop does not provide.
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


def _create_engine() -> AsyncEngine:
    return create_async_engine(
        get_settings().sqlalchemy_database_url,
        pool_pre_ping=True,
    )


engine: AsyncEngine = _create_engine()
SessionFactory: async_sessionmaker[AsyncSession] = async_sessionmaker(
    engine, expire_on_commit=False
)


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency: one session per request, closed when the request ends."""
    async with SessionFactory() as session:
        yield session


@asynccontextmanager
async def session_scope() -> AsyncIterator[AsyncSession]:
    """Context manager for workers/scripts: commits on success, rolls back on error."""
    async with SessionFactory() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
        await session.commit()


async def dispose_engine() -> None:
    """Close the engine's connection pool (call on application shutdown)."""
    await engine.dispose()
