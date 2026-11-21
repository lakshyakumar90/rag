"""Validate user-supplied provider base URLs (SSRF guard)."""

import ipaddress
from urllib.parse import urlparse

from core.config import get_settings


class UnsafeBaseURLError(ValueError):
    """The URL points at a loopback/private/link-local address."""


def validate_base_url(url: str) -> str:
    """Require an http(s) URL; block local/private ranges unless local mode."""
    parsed = urlparse(url.strip())
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise UnsafeBaseURLError("base_url must be an http(s) URL with a host")
    if parsed.username or parsed.password:
        raise UnsafeBaseURLError("base_url must not contain credentials")
    if get_settings().local_mode_enabled:
        return url.strip().rstrip("/")

    host = parsed.hostname.lower().rstrip(".")
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        # DNS names are allowed; literal local names are not. DNS rebinding
        # cannot be prevented at validation time, so resolution happens in the
        # egress layer in production.
        if host == "localhost" or host.endswith(".localhost"):
            raise UnsafeBaseURLError("localhost is not allowed for base_url") from None
        return url.strip().rstrip("/")

    if (
        address.is_loopback
        or address.is_private
        or address.is_link_local
        or address.is_reserved
        or address.is_multicast
        or address.is_unspecified
    ):
        raise UnsafeBaseURLError("private or local IP ranges are not allowed")
    return url.strip().rstrip("/")
