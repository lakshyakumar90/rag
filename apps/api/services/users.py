"""User profile business logic."""

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from models import User
from repositories import UserRepository
from schemas import UserUpdate
from services.exceptions import InvalidAccessTokenError


class UserService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._users = UserRepository(session)

    async def get_active_by_id(self, user_id: uuid.UUID) -> User:
        """Resolve a token subject to a usable user."""
        user = await self._users.get_by_id(user_id)
        if user is None or not user.is_active:
            raise InvalidAccessTokenError()
        return user

    async def update_profile(self, user: User, payload: UserUpdate) -> User:
        changes = payload.model_dump(exclude_unset=True)
        for field, value in changes.items():
            setattr(user, field, value)
        if changes:
            await self._session.commit()
        return user
