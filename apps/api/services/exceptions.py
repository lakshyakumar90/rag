"""Domain-level errors raised by services, mapped to HTTP by core.exceptions."""

from core.exceptions import DomainError

_BEARER_HEADER = {"WWW-Authenticate": "Bearer"}


class EmailAlreadyExistsError(DomainError):
    status_code = 409
    code = "EMAIL_ALREADY_REGISTERED"
    message = "An account with this email already exists"


class InvalidCredentialsError(DomainError):
    status_code = 401
    code = "INVALID_CREDENTIALS"
    message = "Invalid email or password"
    headers = _BEARER_HEADER


class InactiveAccountError(DomainError):
    status_code = 401
    code = "ACCOUNT_INACTIVE"
    message = "This account is inactive"
    headers = _BEARER_HEADER


class InvalidAccessTokenError(DomainError):
    status_code = 401
    code = "INVALID_ACCESS_TOKEN"
    message = "Missing, invalid, or expired access token"
    headers = _BEARER_HEADER


class InvalidRefreshTokenError(DomainError):
    status_code = 401
    code = "INVALID_REFRESH_TOKEN"
    message = "Missing, invalid, or expired refresh token"


class RefreshTokenReuseError(DomainError):
    status_code = 401
    code = "REFRESH_TOKEN_REUSE_DETECTED"
    message = "Refresh token reuse detected; all sessions were revoked"


class IncorrectPasswordError(DomainError):
    status_code = 400
    code = "INCORRECT_CURRENT_PASSWORD"
    message = "The current password is incorrect"


class SamePasswordError(DomainError):
    status_code = 400
    code = "NEW_PASSWORD_SAME_AS_CURRENT"
    message = "The new password must differ from the current password"
