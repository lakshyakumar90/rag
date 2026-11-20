"""Refresh-token cookie handling.

The refresh token is HttpOnly so client JavaScript cannot read it, Secure so
it is only sent over HTTPS, and SameSite to blunt cross-site request forgery.
The body fallback in ``refresh_token_from_request`` exists for non-browser
clients (CLI/tests); browsers always use the cookie.
"""

from fastapi import Request, Response

from core.config import get_settings
from schemas import RefreshRequest


def set_refresh_cookie(response: Response, token: str) -> None:
    settings = get_settings()
    response.set_cookie(
        key=settings.refresh_cookie_name,
        value=token,
        max_age=settings.refresh_token_ttl_days * 24 * 60 * 60,
        path=settings.refresh_cookie_path,
        httponly=True,
        secure=settings.refresh_cookie_secure,
        samesite=settings.refresh_cookie_samesite,
    )


def delete_refresh_cookie(response: Response) -> None:
    settings = get_settings()
    response.delete_cookie(
        key=settings.refresh_cookie_name,
        path=settings.refresh_cookie_path,
        httponly=True,
        secure=settings.refresh_cookie_secure,
        samesite=settings.refresh_cookie_samesite,
    )


def refresh_token_from_request(
    request: Request, payload: RefreshRequest | None
) -> str | None:
    settings = get_settings()
    return request.cookies.get(settings.refresh_cookie_name) or (
        payload.refresh_token if payload else None
    )
