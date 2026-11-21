"""Domain-level errors raised by services, mapped to HTTP by core.exceptions."""

import uuid

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


class WorkspaceSlugAlreadyExistsError(DomainError):
    status_code = 409
    code = "WORKSPACE_SLUG_EXISTS"
    message = "A workspace with this slug already exists"


class WorkspaceNotFoundError(DomainError):
    status_code = 404
    code = "WORKSPACE_NOT_FOUND"
    message = "Workspace not found"


class NotWorkspaceMemberError(DomainError):
    status_code = 403
    code = "NOT_WORKSPACE_MEMBER"
    message = "You are not a member of this workspace"


class OwnerRequiredError(DomainError):
    status_code = 403
    code = "OWNER_REQUIRED"
    message = "Only a workspace owner can perform this action"


class FileTooLargeError(DomainError):
    status_code = 413
    code = "FILE_TOO_LARGE"
    message = "The uploaded file exceeds the size limit"

    def __init__(self, max_bytes: int) -> None:
        super().__init__(self.message)
        self.details = {"max_size_bytes": max_bytes}


class UnsupportedFileTypeError(DomainError):
    status_code = 415
    code = "UNSUPPORTED_FILE_TYPE"
    message = "File type is not allowed or does not match the file content"

    def __init__(self, reason: str) -> None:
        super().__init__(reason)


class DuplicateDocumentError(DomainError):
    status_code = 409
    code = "DUPLICATE_DOCUMENT"
    message = "This file has already been uploaded to this workspace"

    def __init__(self, document_id: uuid.UUID) -> None:
        super().__init__(self.message)
        self.details = {"document_id": str(document_id)}


class DocumentNotFoundError(DomainError):
    status_code = 404
    code = "DOCUMENT_NOT_FOUND"
    message = "Document not found"


class StorageUnavailableError(DomainError):
    status_code = 503
    code = "STORAGE_UNAVAILABLE"
    message = "Object storage is unavailable; please try again later"


class InsufficientRoleError(DomainError):
    status_code = 403
    code = "INSUFFICIENT_ROLE"
    message = "Your role in this workspace does not allow this action"

    def __init__(self, required: list[str], current: str) -> None:
        super().__init__(self.message)
        self.details = {"required_roles": required, "current_role": current}


class LastOwnerError(DomainError):
    status_code = 409
    code = "LAST_OWNER"
    message = "A workspace must keep at least one owner"


class MemberNotFoundError(DomainError):
    status_code = 404
    code = "MEMBER_NOT_FOUND"
    message = "This user is not a member of the workspace"


class AlreadyMemberError(DomainError):
    status_code = 409
    code = "ALREADY_A_MEMBER"
    message = "This user is already a member of the workspace"


class InvitationNotFoundError(DomainError):
    status_code = 404
    code = "INVITATION_NOT_FOUND"
    message = "Invitation not found"


class InvitationExpiredError(DomainError):
    status_code = 410
    code = "INVITATION_EXPIRED"
    message = "This invitation has expired"


class InvitationUnavailableError(DomainError):
    status_code = 409
    code = "INVITATION_UNAVAILABLE"
    message = "This invitation is no longer pending"


class InvitationEmailMismatchError(DomainError):
    status_code = 403
    code = "INVITATION_EMAIL_MISMATCH"
    message = "This invitation was issued for a different email address"
