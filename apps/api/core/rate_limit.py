"""Login rate limiting backed by Redis counters.

Counters are kept per client IP and per (hashed) email so an attacker cannot
make unlimited guesses by rotating either one. Redis failures fail open — the
app remains usable and the outage is logged — because a hard dependency on
Redis for login would turn a cache outage into a full authentication outage.
"""

import hashlib
import ipaddress
import logging
import uuid
from collections.abc import Awaitable
from typing import cast

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


class UserRateLimitExceededError(DomainError):
    status_code = 429
    code = "USER_RATE_LIMIT_EXCEEDED"
    message = "Rate limit exceeded for this action"

    def __init__(self, action: str, retry_after: int) -> None:
        super().__init__(f"{action} rate limit exceeded; try again later")
        self.headers = {"Retry-After": str(retry_after)}
        self.details = {"action": action, "retry_after_seconds": retry_after}


class RateLimitUnavailableError(DomainError):
    status_code = 503
    code = "RATE_LIMIT_UNAVAILABLE"
    message = "Rate limiting is temporarily unavailable; please try again"


class RateLimitExceededError(DomainError):
    status_code = 429
    code = "RATE_LIMIT_EXCEEDED"
    message = "Too many login attempts. Try again later."

    def __init__(self, retry_after: int) -> None:
        super().__init__(self.message)
        self.headers = {"Retry-After": str(retry_after)}
        self.details = {"retry_after_seconds": retry_after}


def _is_trusted_proxy(peer_host: str, cidrs_csv: str) -> bool:
    if not peer_host or peer_host == "unknown":
        return False
    try:
        peer_ip = ipaddress.ip_address(peer_host)
    except ValueError:
        return False
    for raw in cidrs_csv.split(","):
        cidr = raw.strip()
        if not cidr:
            continue
        try:
            if peer_ip in ipaddress.ip_network(cidr, strict=False):
                return True
        except ValueError:
            continue
    return False


def client_ip(request: Request) -> str:
    """Client address, trusting X-Forwarded-For only from configured proxy CIDRs."""
    settings = get_settings()
    peer = request.client.host if request.client else "unknown"
    if settings.trust_proxy_headers and _is_trusted_proxy(
        peer, settings.trusted_proxy_cidrs
    ):
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            return forwarded.split(",", 1)[0].strip() or peer
    return peer


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
            # redis 5.x types `eval` as possibly returning a str; our Lua
            # script always returns a list of integers.
            result = await cast(
                Awaitable[list[int]],
                self._redis.eval(
                    _INCREMENT_SCRIPT,
                    2,
                    keys[0],
                    keys[1],
                    str(self._settings.login_rate_limit_window_seconds),
                ),
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


class UserRateLimiter:
    """Per-user quota for metered actions.

    Unlike login throttling, this fails closed: if Redis is unreachable we
    refuse the action rather than allowing unbounded metered calls.
    """

    def __init__(
        self, redis_client: Redis, action: str, limit: int, window_seconds: int
    ) -> None:
        self._redis = redis_client
        self.action = action
        self.limit = limit
        self.window = window_seconds

    @classmethod
    def chat(
        cls, redis_client: Redis, settings: Settings | None = None
    ) -> "UserRateLimiter":
        settings = settings or get_settings()
        return cls(
            redis_client,
            "chat",
            settings.chat_rate_limit_max,
            settings.chat_rate_limit_window_seconds,
        )

    @classmethod
    def upload(
        cls, redis_client: Redis, settings: Settings | None = None
    ) -> "UserRateLimiter":
        settings = settings or get_settings()
        return cls(
            redis_client,
            "upload",
            settings.upload_rate_limit_max,
            settings.upload_rate_limit_window_seconds,
        )

    async def check(self, user_id: uuid.UUID) -> None:
        key = f"ratelimit:user:{user_id}:{self.action}"
        try:
            result = await cast(
                Awaitable[list[int]],
                self._redis.eval(_INCREMENT_SCRIPT, 1, key, str(self.window)),
            )
        except RedisError as exc:
            logger.error("rate limiter unavailable for %s", self.action, exc_info=exc)
            raise RateLimitUnavailableError() from exc
        count, ttl = int(result[0]), int(result[1])
        if count > self.limit:
            raise UserRateLimitExceededError(self.action, max(1, ttl))
