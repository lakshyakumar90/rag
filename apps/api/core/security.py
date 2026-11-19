from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

# Argon2id with the library's default parameters. Reuse one hasher instance so
# the parameters stay consistent and no per-call setup is needed.
_hasher = PasswordHasher()


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
