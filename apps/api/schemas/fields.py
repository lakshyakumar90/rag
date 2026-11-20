"""Reusable Pydantic-validated field types shared by request schemas."""

import re
from typing import Annotated

from pydantic import AfterValidator, BeforeValidator

from core.security import validate_password_strength

MAX_EMAIL_LENGTH = 320
MAX_FULL_NAME_LENGTH = 255

# Pragmatic format check: Pydantic's stricter EmailStr would require adding
# email-validator, so we keep the dependency surface small. This rejects the
# common mistakes (no @, no dot in domain, whitespace) without claiming full
# RFC 5322 compliance.
_EMAIL_PATTERN = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")


def _normalize_email(value: str) -> str:
    if not isinstance(value, str):
        raise ValueError("email must be a string")
    email = value.strip().lower()
    if not email:
        raise ValueError("email is required")
    if len(email) > MAX_EMAIL_LENGTH:
        raise ValueError(f"email must be at most {MAX_EMAIL_LENGTH} characters long")
    if not _EMAIL_PATTERN.fullmatch(email):
        raise ValueError("enter a valid email address")
    return email


def _normalize_full_name(value: str | None) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("full_name must be a string or null")
    normalized = value.strip()
    if len(normalized) > MAX_FULL_NAME_LENGTH:
        raise ValueError(
            f"full_name must be at most {MAX_FULL_NAME_LENGTH} characters long"
        )
    return normalized or None


EmailAddress = Annotated[str, BeforeValidator(_normalize_email)]
StrongPassword = Annotated[str, AfterValidator(validate_password_strength)]
OptionalFullName = Annotated[str | None, BeforeValidator(_normalize_full_name)]
