"""Login rate limiting backed by Redis counters.

Counters are kept per client IP and per (hashed) email so an attacker cannot
make unlimited guesses by rotating either one. Redis failures fail open — the
app remains usable and the outage is logged — because a hard dependency on
Redis for login would turn a cache outage into a full authentication outage.
"""

import hashlib
import logging

from fastapi import Request
from redis.asyncio import Redis
from redis.exceptions import RedisError

from core.config import Settings, get_settings
from core.exceptions import DomainError

logger = logging.getLogger(__name__)

# INCR + first-EXPIRE + TTL for both keys in one atomic round trip.
_INCREMENT_SCRIPT = """
local result = {}
for i = 1, #KEYS do
    local count = redis.call('INCR', KEYS[i])
    if count == 1 then
        redis.call('EXPIRE', KEYS[i], ARGV[1])
    end
    table.insert(result, count)
    table.insert(result, redis.call('TTL', KEYS[i]))
end
return result
"""


class RateLimitExceededError(DomainError):
    status_code = 429
    code = "RATE_LIMIT_EXCEEDED"
    message = "Too many login attempts. Try again later."

    def __init__(self, retry_after: int) -> None:
        super().__init__(self.message)
        self.headers = {"Retry-After": str(retry_after)}
        self.details = {"retry_after_seconds": retry_after}


def client_ip(request: Request) -> str:
    """Client address, optionally from a trusted proxy's forwarded header."""
    settings = get_settings()
    if settings.trust_proxy_headers:
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            return forwarded.split(",", 1)[0].strip() or "unknown"
    return request.client.host if request.client else "unknown"


class LoginRateLimiter:
    def __init__(self, redis_client: Redis, settings: Settings | None = None) -> None:
        self._redis = redis_client
        self._settings = settings or get_settings()

    @staticmethod
    def _keys(ip: str, email: str) -> tuple[str, str]:
        # Avoid storing a raw email address in Redis key names.
        email_hash = hashlib.sha256(email.strip().lower().encode("utf-8")).hexdigest()
        return f"ratelimit:login:ip:{ip}", f"ratelimit:login:email:{email_hash}"

    async def check(self, ip: str, email: str) -> None:
        """Count this attempt and reject it if the window limit is exceeded."""
        keys = self._keys(ip, email)
        try:
            result = await self._redis.eval(
                _INCREMENT_SCRIPT,
                2,
                keys[0],
                keys[1],
                self._settings.login_rate_limit_window_seconds,
            )
        except RedisError as exc:
            logger.warning(
                "login rate limiter unavailable; allowing attempt",
                extra={"error": str(exc)},
            )
            return

        counts = (int(result[0]), int(result[2]))
        ttls = (int(result[1]), int(result[3]))
        exceeded = [
            ttl
            for count, ttl in zip(counts, ttls, strict=True)
            if count > self._settings.login_rate_limit_max_attempts
        ]
        if exceeded:
            raise RateLimitExceededError(max(1, max(exceeded)))

    async def clear(self, ip: str, email: str) -> None:
        """Reset both counters after a successful login."""
        try:
            await self._redis.delete(*self._keys(ip, email))
        except RedisError as exc:
            logger.warning(
                "login rate limiter unavailable; skipping counter reset",
                extra={"error": str(exc)},
            )
