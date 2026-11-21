"""Fernet encryption for user-supplied API keys."""

import logging

from cryptography.fernet import Fernet, InvalidToken

from core.config import get_settings

logger = logging.getLogger(__name__)


class EncryptionUnavailableError(Exception):
    """The master key is missing or invalid."""


def _fernet() -> Fernet:
    key = get_settings().llm_master_key
    if not key:
        raise EncryptionUnavailableError("LLM_MASTER_KEY is not configured")
    try:
        return Fernet(key.encode())
    except (ValueError, TypeError) as exc:
        raise EncryptionUnavailableError(
            "LLM_MASTER_KEY is not a valid Fernet key"
        ) from exc


def encrypt_secret(value: str) -> str:
    """Return a Fernet token for ``value``."""
    return _fernet().encrypt(value.encode()).decode()


def decrypt_secret(token: str) -> str:
    """Reverse :func:`encrypt_secret`; never call this from serializers."""
    try:
        return _fernet().decrypt(token.encode()).decode()
    except InvalidToken as exc:
        raise EncryptionUnavailableError(
            "stored secret could not be decrypted"
        ) from exc


def key_last4(value: str) -> str:
    """Return only the last four characters for display."""
    return value[-4:]
