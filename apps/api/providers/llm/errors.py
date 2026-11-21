"""Map provider HTTP failures onto the shared error taxonomy."""

import json

import httpx

from providers.llm.types import (
    AuthenticationError,
    ContextLengthError,
    ProviderAPIError,
    RateLimitError,
)

_CONTEXT_HINTS = (
    "context length",
    "maximum context",
    "context window",
    "too long",
    "token limit",
    "max_tokens",
)


def _message(body: str) -> str:
    """Extract a readable message from a JSON error body, or trim raw text."""
    try:
        data = json.loads(body)
    except (json.JSONDecodeError, TypeError):
        return body[:300]
    if not isinstance(data, dict):
        return str(data)[:300]
    error = data.get("error", data)
    if isinstance(error, dict):
        return str(error.get("message") or error.get("type") or data)[:300]
    return str(error)[:300]


def map_http_error(
    status: int, body: str, headers: httpx.Headers | None = None
) -> ProviderAPIError:
    """Translate an error status/body into a normalized exception."""
    message = _message(body)
    lower = message.lower()
    if status in (401, 403):
        return AuthenticationError(message, status_code=status)
    if status == 429:
        return RateLimitError(
            message,
            status_code=status,
            retry_after=headers.get("retry-after") if headers else None,
        )
    if status in (400, 413, 422) and any(hint in lower for hint in _CONTEXT_HINTS):
        return ContextLengthError(message, status_code=status)
    return ProviderAPIError(message, status_code=status)
