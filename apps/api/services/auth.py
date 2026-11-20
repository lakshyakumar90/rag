"""Authentication business logic: registration, login, token lifecycle."""

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import get_settings
from core.security import InvalidTokenError as SecurityInvalidTokenError
from core.security import (
    TokenType,
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    hash_refresh_token,
    needs_rehash,
    verify_password,
)
from models import RefreshToken, User
from repositories import RefreshTokenRepository, UserRepository
from schemas import RegisterRequest, TokenPair
from services.exceptions import (
    EmailAlreadyExistsError,
    InactiveAccountError,
    IncorrectPasswordError,
    InvalidAccessTokenError,
    InvalidCredentialsError,
    InvalidRefreshTokenError,
    RefreshTokenReuseError,
    SamePasswordError,
)

# Verified against a missing user's email so that "unknown email" and "wrong
# password" take roughly the same time, avoiding a timing-based user oracle.
_DUMMY_PASSWORD_HASH = hash_password("timing-equalization-placeholder")


class AuthService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._users = UserRepository(session)
        self._refresh_tokens = RefreshTokenRepository(session)

    async def register(self, payload: RegisterRequest) -> User:
        if await self._users.get_by_email(payload.email) is not None:
            raise EmailAlreadyExistsError()

        user = User(
            email=payload.email,
            full_name=payload.full_name,
            password_hash=hash_password(payload.password),
        )
        await self._users.add(user)
        try:
            await self._session.commit()
        except IntegrityError as exc:
            # Concurrent registration with the same email lost the race on the
            # unique index; report the same outcome as the pre-check.
            await self._session.rollback()
            raise EmailAlreadyExistsError() from exc
        return user

    async def authenticate(
        self, email: str, password: str, user_agent: str | None = None
    ) -> TokenPair:
        user = await self._users.get_by_email(email)
        stored_hash = user.password_hash if user is not None else _DUMMY_PASSWORD_HASH
        if not verify_password(password, stored_hash) or user is None:
            raise InvalidCredentialsError()
        if not user.is_active:
            raise InactiveAccountError()

        # Transparently upgrade hashes created under older Argon2 parameters.
        if needs_rehash(user.password_hash):
            user.password_hash = hash_password(password)

        pair, refresh_row = self._issue_tokens(user.id, user_agent)
        await self._refresh_tokens.add(refresh_row)
        await self._session.commit()
        return pair

    async def refresh(
        self, refresh_token: str, user_agent: str | None = None
    ) -> TokenPair:
        try:
            payload = decode_token(refresh_token, TokenType.REFRESH)
        except SecurityInvalidTokenError as exc:
            raise InvalidRefreshTokenError() from exc

        # FOR UPDATE serializes concurrent rotation of the same token.
        stored = await self._refresh_tokens.get_by_hash_for_update(
            hash_refresh_token(refresh_token)
        )
        if stored is None:
            raise InvalidRefreshTokenError()
        if stored.revoked:
            # A rotated token should never be presented twice. Treat it as
            # theft and revoke the whole token family before reporting failure.
            await self._refresh_tokens.revoke_all_for_user(stored.user_id)
            await self._session.commit()
            raise RefreshTokenReuseError()

        expires_at = stored.expires_at
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=UTC)
        if expires_at <= datetime.now(UTC) or payload.sub != stored.user_id:
            raise InvalidRefreshTokenError()

        user = await self._users.get_by_id(stored.user_id)
        if user is None or not user.is_active:
            raise InvalidRefreshTokenError()

        # Revoke the old token and persist its replacement in one transaction:
        # a failed commit leaves the original token usable.
        stored.revoked = True
        pair, new_row = self._issue_tokens(user.id, user_agent)
        await self._refresh_tokens.add(new_row)
        await self._session.commit()
        return pair

    async def logout(self, refresh_token: str) -> None:
        """Revoke one refresh token. Idempotent for unknown/revoked tokens."""
        stored = await self._refresh_tokens.get_by_hash(
            hash_refresh_token(refresh_token)
        )
        if stored is not None and not stored.revoked:
            stored.revoked = True
            await self._session.commit()

    async def change_password(
        self, user: User, current_password: str, new_password: str
    ) -> None:
        if not verify_password(current_password, user.password_hash):
            raise IncorrectPasswordError()
        if verify_password(new_password, user.password_hash):
            raise SamePasswordError()

        user.password_hash = hash_password(new_password)
        # Changing the password invalidates every existing session; users must
        # log in again with the new password.
        await self._refresh_tokens.revoke_all_for_user(user.id)
        await self._session.commit()

    def verify_access_token(self, token: str) -> uuid.UUID:
        """Validate an access token and return the subject user ID."""
        try:
            payload = decode_token(token, TokenType.ACCESS)
        except SecurityInvalidTokenError as exc:
            raise InvalidAccessTokenError() from exc
        return payload.sub

    @staticmethod
    def _issue_tokens(
        user_id: uuid.UUID, user_agent: str | None
    ) -> tuple[TokenPair, RefreshToken]:
        """Build a token pair and the refresh-token row to persist with it."""
        settings = get_settings()
        access_token = create_access_token(user_id)
        refresh_token = create_refresh_token(user_id)
        pair = TokenPair(
            access_token=access_token,
            refresh_token=refresh_token,
            expires_in=settings.access_token_ttl_minutes * 60,
            refresh_expires_in=settings.refresh_token_ttl_days * 24 * 60 * 60,
        )
        row = RefreshToken(
            user_id=user_id,
            token_hash=hash_refresh_token(refresh_token),
            expires_at=datetime.now(UTC)
            + timedelta(days=settings.refresh_token_ttl_days),
            user_agent=user_agent,
        )
        return pair, row
