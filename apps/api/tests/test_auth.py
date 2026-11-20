"""End-to-end auth tests: register, login, cookies, rotation, rate limiting."""

import uuid
from datetime import UTC, datetime, timedelta

import jwt
import pytest
from httpx import AsyncClient

from core.config import get_settings
from core.security import TokenType

BASE = "/api/v1"
EMAIL = "user@example.com"
STRONG_PASSWORD = "StrongPassw0rd!"
COOKIE_NAME = "refresh_token"


def _token(token_type: TokenType, *, expired: bool = False) -> str:
    """Mint a well-formed JWT that bypasses the normal TTL settings."""
    now = datetime.now(UTC)
    payload = {
        "sub": str(uuid.uuid4()),
        "type": token_type.value,
        "iat": now - timedelta(minutes=10),
        "exp": now - timedelta(seconds=1) if expired else now + timedelta(minutes=5),
        "jti": str(uuid.uuid4()),
    }
    settings = get_settings()
    return jwt.encode(
        payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm
    )


@pytest.fixture
async def registered(client: AsyncClient) -> dict[str, object]:
    response = await client.post(
        f"{BASE}/auth/register",
        json={"email": EMAIL, "password": STRONG_PASSWORD, "full_name": "Test User"},
    )
    assert response.status_code == 201, response.text
    return response.json()


async def _login(client: AsyncClient) -> dict[str, object]:
    response = await client.post(
        f"{BASE}/auth/login", json={"email": EMAIL, "password": STRONG_PASSWORD}
    )
    assert response.status_code == 200, response.text
    return response.json()


def _cookie(token: str) -> dict[str, str]:
    """Explicit Cookie header (httpx's jar is unreliable for manual cookies)."""
    return {"Cookie": f"{COOKIE_NAME}={token}"}


async def test_register(client: AsyncClient) -> None:
    response = await client.post(
        f"{BASE}/auth/register",
        json={"email": " NEW@Example.com ", "password": STRONG_PASSWORD},
    )
    assert response.status_code == 201
    body = response.json()
    assert body["email"] == "new@example.com"
    assert "password_hash" not in body
    assert body["is_active"] is True


async def test_register_rejects_weak_password(client: AsyncClient) -> None:
    response = await client.post(
        f"{BASE}/auth/register",
        json={"email": EMAIL, "password": "password"},
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


async def test_login_sets_httponly_secure_cookie_without_body_token(
    client: AsyncClient, registered: dict[str, object]
) -> None:
    body = await _login(client)
    assert "refresh_token" not in body
    assert body["token_type"] == "bearer"
    assert int(str(body["expires_in"])) > 0

    set_cookie = client.cookies
    assert set_cookie.get(COOKIE_NAME) is not None
    # Inspect the raw header for the security flags.
    response = await client.post(
        f"{BASE}/auth/login", json={"email": EMAIL, "password": STRONG_PASSWORD}
    )
    header = response.headers.get("set-cookie", "")
    assert "HttpOnly" in header
    assert "Secure" in header
    assert "SameSite=lax" in header
    assert "Path=/api/v1/auth" in header


async def test_login_wrong_password(
    client: AsyncClient, registered: dict[str, object]
) -> None:
    response = await client.post(
        f"{BASE}/auth/login", json={"email": EMAIL, "password": "WrongPass1!"}
    )
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "INVALID_CREDENTIALS"
    assert response.headers["www-authenticate"] == "Bearer"


async def test_protected_route_rejects_bad_tokens(
    client: AsyncClient, registered: dict[str, object]
) -> None:
    for headers in (
        {},
        {"Authorization": "Bearer not-a-jwt"},
        {"Authorization": f"Bearer {_token(TokenType.REFRESH)}"},
    ):
        response = await client.get(f"{BASE}/users/me", headers=headers)
        assert response.status_code == 401, response.text
        assert response.json()["error"]["code"] == "INVALID_ACCESS_TOKEN"


async def test_protected_route_rejects_expired_token(
    client: AsyncClient, registered: dict[str, object]
) -> None:
    response = await client.get(
        f"{BASE}/users/me",
        headers={"Authorization": f"Bearer {_token(TokenType.ACCESS, expired=True)}"},
    )
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "INVALID_ACCESS_TOKEN"


async def test_protected_route_accepts_valid_token(
    client: AsyncClient, registered: dict[str, object]
) -> None:
    body = await _login(client)
    response = await client.get(
        f"{BASE}/users/me",
        headers={"Authorization": f"Bearer {body['access_token']}"},
    )
    assert response.status_code == 200
    assert response.json()["email"] == EMAIL


async def test_refresh_rotates_cookie_and_rejects_reuse(
    client: AsyncClient, registered: dict[str, object]
) -> None:
    await _login(client)
    first = client.cookies.get(COOKIE_NAME)
    assert first is not None

    response = await client.post(f"{BASE}/auth/refresh")
    assert response.status_code == 200, response.text
    assert "refresh_token" not in response.json()
    second = client.cookies.get(COOKIE_NAME)
    assert second is not None and second != first

    # Replaying the rotated token revokes the whole family.
    response = await client.post(f"{BASE}/auth/refresh", headers=_cookie(first))
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "REFRESH_TOKEN_REUSE_DETECTED"

    response = await client.post(f"{BASE}/auth/refresh", headers=_cookie(second))
    assert response.status_code == 401


async def test_expired_refresh_token_is_rejected(client: AsyncClient) -> None:
    response = await client.post(
        f"{BASE}/auth/refresh",
        headers=_cookie(_token(TokenType.REFRESH, expired=True)),
    )
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "INVALID_REFRESH_TOKEN"


async def test_logout_revokes_token_and_clears_cookie(
    client: AsyncClient, registered: dict[str, object]
) -> None:
    await _login(client)
    token = client.cookies.get(COOKIE_NAME)
    assert token is not None

    response = await client.post(f"{BASE}/auth/logout")
    assert response.status_code == 204
    assert client.cookies.get(COOKIE_NAME) is None

    response = await client.post(f"{BASE}/auth/refresh", headers=_cookie(token))
    assert response.status_code == 401


async def test_login_rate_limit_blocks_excessive_failures(
    client: AsyncClient, registered: dict[str, object]
) -> None:
    for _ in range(5):
        response = await client.post(
            f"{BASE}/auth/login", json={"email": EMAIL, "password": "WrongPass1!"}
        )
        assert response.status_code == 401

    response = await client.post(
        f"{BASE}/auth/login", json={"email": EMAIL, "password": "WrongPass1!"}
    )
    assert response.status_code == 429
    assert response.json()["error"]["code"] == "RATE_LIMIT_EXCEEDED"
    assert int(response.headers["retry-after"]) > 0

    # Even correct credentials are blocked until the window clears.
    response = await client.post(
        f"{BASE}/auth/login", json={"email": EMAIL, "password": STRONG_PASSWORD}
    )
    assert response.status_code == 429
