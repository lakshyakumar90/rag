"""FastAPI dependencies shared by the v1 endpoints."""

import uuid
from collections.abc import Awaitable, Callable
from typing import Annotated

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import SessionFactory, get_session
from core.rate_limit import LoginRateLimiter, UserRateLimiter
from core.redis import get_redis_client
from models import MembershipRole, User
from providers.embeddings import EmbeddingProvider, get_embedding_provider
from providers.minio import MinioStorageClient
from providers.qdrant import shared_qdrant_client
from providers.queue import ArqJobQueue, JobQueue, get_arq_pool
from providers.rerank import Reranker
from providers.storage import StorageClient
from services import (
    AccountService,
    AgentService,
    AISettingsService,
    AuthService,
    ChatService,
    ConversationService,
    DocumentAccessService,
    DocumentService,
    EmbeddingProfileService,
    FeedbackService,
    ProviderConfigService,
    RetrievalService,
    UsageService,
    UserService,
    WorkspaceService,
)
from services.exceptions import (
    InsufficientRoleError,
    InvalidAccessTokenError,
    OwnerRequiredError,
)
from services.qdrant_index import QdrantIndexService
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


def get_chat_rate_limiter(
    redis_client: Annotated[Redis, Depends(get_redis_client)],
) -> UserRateLimiter:
    return UserRateLimiter.chat(redis_client)


def get_upload_rate_limiter(
    redis_client: Annotated[Redis, Depends(get_redis_client)],
) -> UserRateLimiter:
    return UserRateLimiter.upload(redis_client)


def get_storage_client() -> StorageClient:
    return MinioStorageClient()


def get_job_queue() -> JobQueue:
    return ArqJobQueue(get_arq_pool())


async def get_qdrant_indexer() -> QdrantIndexService | None:
    """Shared Qdrant indexer, or None while the backfill is not enabled."""
    from core.config import get_settings

    if not get_settings().qdrant_enabled:
        return None
    return QdrantIndexService(await shared_qdrant_client(), SessionFactory)


def get_document_service(
    session: Annotated[AsyncSession, Depends(get_session)],
    storage: Annotated[StorageClient, Depends(get_storage_client)],
    queue: Annotated[JobQueue, Depends(get_job_queue)],
    indexer: Annotated[QdrantIndexService | None, Depends(get_qdrant_indexer)],
) -> DocumentService:
    return DocumentService(session, storage, queue, indexer)


def get_document_access_service(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> DocumentAccessService:
    return DocumentAccessService(session)


def get_provider_config_service(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ProviderConfigService:
    return ProviderConfigService(session)


def get_reranker() -> Reranker:
    return Reranker()


def get_retrieval_service(
    session: Annotated[AsyncSession, Depends(get_session)],
    embeddings: Annotated[EmbeddingProvider, Depends(get_embedding_provider)],
    reranker: Annotated[Reranker, Depends(get_reranker)],
    indexer: Annotated[QdrantIndexService | None, Depends(get_qdrant_indexer)],
) -> RetrievalService:
    return RetrievalService(session, embeddings, reranker, indexer)


def get_conversation_service(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ConversationService:
    return ConversationService(session)


def get_embedding_profile_service(
    session: Annotated[AsyncSession, Depends(get_session)],
    queue: Annotated[JobQueue, Depends(get_job_queue)],
    indexer: Annotated[QdrantIndexService | None, Depends(get_qdrant_indexer)],
) -> EmbeddingProfileService:
    return EmbeddingProfileService(session, queue, indexer)


def get_ai_settings_service(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> AISettingsService:
    return AISettingsService(session)


def get_chat_service(
    retrieval: Annotated[RetrievalService, Depends(get_retrieval_service)],
    conversations: Annotated[ConversationService, Depends(get_conversation_service)],
    defaults: Annotated[AISettingsService, Depends(get_ai_settings_service)],
) -> ChatService:
    return ChatService(retrieval, conversations, defaults)


def get_agent_service(
    retrieval: Annotated[RetrievalService, Depends(get_retrieval_service)],
    defaults: Annotated[AISettingsService, Depends(get_ai_settings_service)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> AgentService:
    return AgentService(session, retrieval, defaults)


def get_feedback_service(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> FeedbackService:
    return FeedbackService(session)


def get_usage_service(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> UsageService:
    return UsageService(session)


def get_account_service(
    session: Annotated[AsyncSession, Depends(get_session)],
    storage: Annotated[StorageClient, Depends(get_storage_client)],
) -> AccountService:
    return AccountService(session, storage)


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
#: Analytics and audit are visible to owners and admins.
AdminContext = InviterContext

# Same role rule for documents: only owners and admins manage files.
_require_uploader = require_role(MembershipRole.OWNER, MembershipRole.ADMIN)
UploaderContext = Annotated[WorkspaceContext, Depends(_require_uploader)]
