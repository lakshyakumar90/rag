"""Auth endpoints: register, login, refresh (rotation), logout, password change."""

from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response, status

from api.v1.cookies import (
    delete_refresh_cookie,
    refresh_token_from_request,
    set_refresh_cookie,
)
from api.v1.dependencies import (
    CurrentUser,
    get_auth_service,
    get_login_rate_limiter,
)
from core.rate_limit import LoginRateLimiter, client_ip
from models import User
from schemas import (
    ChangePasswordRequest,
    LoginRequest,
    RefreshRequest,
    RegisterRequest,
    TokenPair,
    TokenResponse,
    UserResponse,
)
from services import AuthService
from services.exceptions import InvalidRefreshTokenError

router = APIRouter(prefix="/auth", tags=["auth"])


def _public_token_response(pair: TokenPair) -> TokenResponse:
    """Copy token metadata without exposing the refresh token to clients."""
    return TokenResponse(
        access_token=pair.access_token,
        token_type=pair.token_type,
        expires_in=pair.expires_in,
        refresh_expires_in=pair.refresh_expires_in,
    )


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
    "/login", response_model=TokenResponse, summary="Exchange credentials for tokens"
)
async def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    service: Annotated[AuthService, Depends(get_auth_service)],
    limiter: Annotated[LoginRateLimiter, Depends(get_login_rate_limiter)],
) -> TokenResponse:
    ip = client_ip(request)
    await limiter.check(ip, payload.email)
    # A failed authentication leaves the counters in place; only success
    # resets them.
    pair = await service.authenticate(
        payload.email, payload.password, request.headers.get("user-agent")
    )
    await limiter.clear(ip, payload.email)
    set_refresh_cookie(response, pair.refresh_token)
    return _public_token_response(pair)


@router.post(
    "/refresh",
    response_model=TokenResponse,
    summary="Rotate a refresh token (the old one is revoked)",
)
async def refresh(
    request: Request,
    response: Response,
    service: Annotated[AuthService, Depends(get_auth_service)],
    payload: RefreshRequest | None = None,
) -> TokenResponse:
    token = refresh_token_from_request(request, payload)
    if not token:
        raise InvalidRefreshTokenError()
    pair = await service.refresh(token, request.headers.get("user-agent"))
    set_refresh_cookie(response, pair.refresh_token)
    return _public_token_response(pair)


@router.post(
    "/logout",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Revoke a refresh token and clear its cookie",
)
async def logout(
    request: Request,
    response: Response,
    service: Annotated[AuthService, Depends(get_auth_service)],
    payload: RefreshRequest | None = None,
) -> None:
    token = refresh_token_from_request(request, payload)
    if token:
        await service.logout(token)
    delete_refresh_cookie(response)


@router.post(
    "/change-password",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Change the current user's password and revoke all sessions",
)
async def change_password(
    payload: ChangePasswordRequest,
    response: Response,
    current_user: CurrentUser,
    service: Annotated[AuthService, Depends(get_auth_service)],
) -> None:
    await service.change_password(
        current_user, payload.current_password, payload.new_password
    )
    delete_refresh_cookie(response)
