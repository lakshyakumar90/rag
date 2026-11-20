import hashlib
import uuid
from datetime import UTC, datetime, timedelta
from enum import StrEnum

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from pydantic import BaseModel, ValidationError

from core.config import get_settings

# Argon2id with the library's default parameters. Reuse one hasher instance so
# the parameters stay consistent and no per-call setup is needed.
_hasher = PasswordHasher()

# Password policy. A max length bounds hashing cost (and avoids pathological
# inputs); the denylist catches the most common weak passwords without pulling
# in a large breached-password dataset.
MIN_PASSWORD_LENGTH = 8
MAX_PASSWORD_LENGTH = 128
_COMMON_PASSWORDS = frozenset(
    {
        "password",
        "password1",
        "password123",
        "passw0rd",
        "p@ssw0rd",
        "12345678",
        "123456789",
        "1234567890",
        "qwerty",
        "qwerty123",
        "abc12345",
        "letmein",
        "welcome",
        "welcome1",
        "admin123",
        "changeme",
        "iloveyou",
        "monkey",
        "football",
        "dragon",
        "sunshine",
        "princess",
    }
)


def validate_password_strength(password: str) -> str:
    """Return ``password`` if it satisfies the password policy.

    Raises ``ValueError`` with an actionable message otherwise; Pydantic turns
    that into a 422 validation error on the owning field.
    """
    if len(password) < MIN_PASSWORD_LENGTH:
        raise ValueError(
            f"Password must be at least {MIN_PASSWORD_LENGTH} characters long"
        )
    if len(password) > MAX_PASSWORD_LENGTH:
        raise ValueError(
            f"Password must be at most {MAX_PASSWORD_LENGTH} characters long"
        )
    if password.strip().lower() in _COMMON_PASSWORDS:
        raise ValueError("Password is too common; choose a different one")

    missing: list[str] = []
    if not any(char.islower() for char in password):
        missing.append("a lowercase letter")
    if not any(char.isupper() for char in password):
        missing.append("an uppercase letter")
    if not any(char.isdigit() for char in password):
        missing.append("a digit")
    if not any(not char.isalnum() for char in password):
        missing.append("a special character")
    if missing:
        raise ValueError(f"Password must contain {', '.join(missing)}")
    return password


class TokenType(StrEnum):
    ACCESS = "access"
    REFRESH = "refresh"


class TokenPayload(BaseModel):
    sub: uuid.UUID
    type: TokenType
    iat: datetime
    exp: datetime
    jti: uuid.UUID


class InvalidTokenError(Exception):
    """A token is malformed, expired, or does not match the expected type."""


def hash_password(password: str) -> str:
    """Return an Argon2id hash suitable for storing in ``users.password_hash``."""
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    """Check a plaintext password against a stored hash; bad hashes return False."""
    try:
        return _hasher.verify(password_hash, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def needs_rehash(password_hash: str) -> bool:
    """Whether a stored hash should be upgraded to current Argon2 parameters."""
    try:
        return _hasher.check_needs_rehash(password_hash)
    except InvalidHashError:
        return True


def hash_refresh_token(token: str) -> str:
    """Deterministic SHA-256 digest for looking up stored refresh tokens."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _create_token(
    subject: uuid.UUID | str, token_type: TokenType, lifetime: timedelta
) -> str:
    settings = get_settings()
    now = datetime.now(UTC)
    payload = {
        "sub": str(subject),
        "type": token_type.value,
        "iat": now,
        "exp": now + lifetime,
        "jti": str(uuid.uuid4()),
    }
    return jwt.encode(
        payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm
    )


def create_access_token(subject: uuid.UUID | str) -> str:
    """Issue a short-lived access token (default: 15 minutes)."""
    return _create_token(
        subject,
        TokenType.ACCESS,
        timedelta(minutes=get_settings().access_token_ttl_minutes),
    )


def create_refresh_token(subject: uuid.UUID | str) -> str:
    """Issue a long-lived refresh token (default: 7 days)."""
    return _create_token(
        subject,
        TokenType.REFRESH,
        timedelta(days=get_settings().refresh_token_ttl_days),
    )


def decode_token(token: str, expected_type: TokenType) -> TokenPayload:
    """Verify signature/expiry and require a specific ``type`` claim."""
    settings = get_settings()
    try:
        raw = jwt.decode(
            token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm]
        )
        payload = TokenPayload.model_validate(raw)
    except (jwt.PyJWTError, ValidationError) as exc:
        raise InvalidTokenError("invalid or expired token") from exc

    if payload.type != expected_type:
        raise InvalidTokenError(f"expected token type {expected_type.value!r}")
    return payload
