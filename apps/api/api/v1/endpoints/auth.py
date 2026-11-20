"""Auth endpoints: register, login, refresh (rotation), logout, password change."""

from typing import Annotated

from fastapi import APIRouter, Depends, Request, status

from api.v1.dependencies import get_auth_service, get_current_user
from models import User
from schemas import (
    ChangePasswordRequest,
    LoginRequest,
    RefreshRequest,
    RegisterRequest,
    TokenPair,
    UserResponse,
)
from services import AuthService

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post(
    "/register",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create an account (password strength is validated)",
)
async def register(
    payload: RegisterRequest,
    service: Annotated[AuthService, Depends(get_auth_service)],
) -> User:
    return await service.register(payload)


@router.post(
    "/login", response_model=TokenPair, summary="Exchange credentials for tokens"
)
async def login(
    payload: LoginRequest,
    request: Request,
    service: Annotated[AuthService, Depends(get_auth_service)],
) -> TokenPair:
    return await service.authenticate(
        payload.email, payload.password, request.headers.get("user-agent")
    )


@router.post(
    "/refresh",
    response_model=TokenPair,
    summary="Rotate a refresh token (the old one is revoked)",
)
async def refresh(
    payload: RefreshRequest,
    request: Request,
    service: Annotated[AuthService, Depends(get_auth_service)],
) -> TokenPair:
    return await service.refresh(
        payload.refresh_token, request.headers.get("user-agent")
    )


@router.post(
    "/logout",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Revoke a refresh token",
)
async def logout(
    payload: RefreshRequest,
    service: Annotated[AuthService, Depends(get_auth_service)],
) -> None:
    await service.logout(payload.refresh_token)


@router.post(
    "/change-password",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Change the current user's password and revoke all sessions",
)
async def change_password(
    payload: ChangePasswordRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    service: Annotated[AuthService, Depends(get_auth_service)],
) -> None:
    await service.change_password(
        current_user, payload.current_password, payload.new_password
    )
