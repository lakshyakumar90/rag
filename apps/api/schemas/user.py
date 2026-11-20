"""User profile schemas."""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from schemas.fields import OptionalFullName


class UserResponse(BaseModel):
    """Public user representation. Never exposes the password hash."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    full_name: str | None
    is_active: bool
    created_at: datetime
    updated_at: datetime


class UserUpdate(BaseModel):
    """PATCH /users/me payload. Only explicitly provided fields are applied."""

    model_config = ConfigDict(extra="forbid")

    full_name: OptionalFullName = None
