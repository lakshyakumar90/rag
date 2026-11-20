"""FastAPI dependencies shared by the v1 auth/user endpoints."""

import uuid
from typing import Annotated

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_session
from models import User
from services import AuthService, UserService
from services.exceptions import InvalidAccessTokenError

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
