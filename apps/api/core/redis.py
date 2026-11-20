"""Redis client shared by rate limiting (and future cached state)."""

from redis.asyncio import Redis

from core.config import get_settings

_client: Redis | None = None


def get_redis_client() -> Redis:
    """Return a lazily-created client; no connection is made until a command."""
    global _client
    if _client is None:
        _client = Redis.from_url(get_settings().redis_url)
    return _client


async def close_redis_client() -> None:
    """Close the connection pool on application shutdown."""
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None
