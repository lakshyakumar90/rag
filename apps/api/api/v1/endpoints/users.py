"""Current-user profile endpoints."""

from typing import Annotated

from fastapi import APIRouter, Depends

from api.v1.dependencies import get_current_user, get_user_service
from models import User
from schemas import UserResponse, UserUpdate
from services import UserService

router = APIRouter(prefix="/users", tags=["users"])


@router.get("/me", response_model=UserResponse, summary="Get the current user")
async def read_me(
    current_user: Annotated[User, Depends(get_current_user)],
) -> User:
    return current_user


@router.patch("/me", response_model=UserResponse, summary="Update the current user")
async def update_me(
    payload: UserUpdate,
    current_user: Annotated[User, Depends(get_current_user)],
    service: Annotated[UserService, Depends(get_user_service)],
) -> User:
    return await service.update_profile(current_user, payload)
