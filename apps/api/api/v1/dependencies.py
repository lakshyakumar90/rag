"""FastAPI dependencies shared by the v1 endpoints."""

import uuid
from collections.abc import Awaitable, Callable
from typing import Annotated

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_session
from core.rate_limit import LoginRateLimiter
from core.redis import get_redis_client
from models import MembershipRole, User
from providers.minio import MinioStorageClient
from providers.queue import ArqJobQueue, JobQueue, get_arq_pool
from providers.storage import StorageClient
from services import AuthService, DocumentService, UserService, WorkspaceService
from services.exceptions import (
    InsufficientRoleError,
    InvalidAccessTokenError,
    OwnerRequiredError,
)
from services.workspaces import WorkspaceContext

# auto_error=False so a missing/malformed header produces our own structured
# 401 (with WWW-Authenticate) instead of FastAPI's default 403.
_bearer = HTTPBearer(auto_error=False)


def get_auth_service(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> AuthService:
    return AuthService(session)


def get_user_service(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> UserService:
    return UserService(session)


def get_workspace_service(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> WorkspaceService:
    return WorkspaceService(session)


def get_login_rate_limiter(
    redis_client: Annotated[Redis, Depends(get_redis_client)],
) -> LoginRateLimiter:
    return LoginRateLimiter(redis_client)


def get_storage_client() -> StorageClient:
    return MinioStorageClient()


def get_job_queue() -> JobQueue:
    return ArqJobQueue(get_arq_pool())


def get_document_service(
    session: Annotated[AsyncSession, Depends(get_session)],
    storage: Annotated[StorageClient, Depends(get_storage_client)],
    queue: Annotated[JobQueue, Depends(get_job_queue)],
) -> DocumentService:
    return DocumentService(session, storage, queue)


async def get_current_user_id(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    auth_service: Annotated[AuthService, Depends(get_auth_service)],
) -> uuid.UUID:
    if credentials is None:
        raise InvalidAccessTokenError()
    return auth_service.verify_access_token(credentials.credentials)


async def get_current_user(
    user_id: Annotated[uuid.UUID, Depends(get_current_user_id)],
    user_service: Annotated[UserService, Depends(get_user_service)],
) -> User:
    return await user_service.get_active_by_id(user_id)


# Shorthand for protected routes: `current_user: CurrentUser`.
CurrentUser = Annotated[User, Depends(get_current_user)]


async def get_workspace_context(
    workspace_id: uuid.UUID,
    current_user: CurrentUser,
    workspace_service: Annotated[WorkspaceService, Depends(get_workspace_service)],
) -> WorkspaceContext:
    """Resolve the workspace from the path and verify the caller is a member."""
    return await workspace_service.get_context(workspace_id, current_user)


#: Any member of the workspace in the path.
MemberContext = Annotated[WorkspaceContext, Depends(get_workspace_context)]


def require_role(
    *roles: MembershipRole,
    error: type[InsufficientRoleError | OwnerRequiredError] = InsufficientRoleError,
) -> Callable[..., Awaitable[WorkspaceContext]]:
    """Build a dependency that allows only the given workspace roles.

    ``error`` lets owner-only endpoints keep their existing `OWNER_REQUIRED`
    error code while new role combinations use the generic `INSUFFICIENT_ROLE`.
    """

    async def _check(
        context: Annotated[WorkspaceContext, Depends(get_workspace_context)],
    ) -> WorkspaceContext:
        if context.role not in roles:
            if error is OwnerRequiredError:
                raise OwnerRequiredError()
            raise InsufficientRoleError(
                [role.value for role in roles], context.role.value
            )
        return context

    return _check


# Defined once at module level so FastAPI's dependency cache keys stay stable.
_require_owner = require_role(MembershipRole.OWNER, error=OwnerRequiredError)
_require_inviter = require_role(MembershipRole.OWNER, MembershipRole.ADMIN)

#: Owner-only context.
OwnerContext = Annotated[WorkspaceContext, Depends(_require_owner)]
#: Owners and admins may invite; plain members may not.
InviterContext = Annotated[WorkspaceContext, Depends(_require_inviter)]

# Same role rule for documents: only owners and admins manage files.
_require_uploader = require_role(MembershipRole.OWNER, MembershipRole.ADMIN)
UploaderContext = Annotated[WorkspaceContext, Depends(_require_uploader)]
