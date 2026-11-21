"""Workspace, membership and invitation request/response schemas."""

import re
import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, field_validator

from models import InvitationStatus, MembershipRole
from schemas.fields import EmailAddress

MAX_WORKSPACE_NAME = 255
MAX_SLUG = 63
_SLUG_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


def _validate_slug(value: str) -> str:
    """Lowercase and validate a slug (mirrors the ORM validator)."""
    slug = value.strip().lower()
    if not slug:
        raise ValueError("slug is required")
    if len(slug) > MAX_SLUG:
        raise ValueError(f"slug must be at most {MAX_SLUG} characters long")
    if not _SLUG_PATTERN.fullmatch(slug):
        raise ValueError(
            "slug must contain only lowercase letters, digits and single hyphens"
        )
    return slug


class WorkspaceCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    slug: str

    @field_validator("name")
    @classmethod
    def _name(cls, value: str) -> str:
        name = value.strip()
        if not name:
            raise ValueError("name is required")
        if len(name) > MAX_WORKSPACE_NAME:
            raise ValueError(
                f"name must be at most {MAX_WORKSPACE_NAME} characters long"
            )
        return name

    @field_validator("slug")
    @classmethod
    def _slug(cls, value: str) -> str:
        return _validate_slug(value)


class WorkspaceUpdate(BaseModel):
    """PATCH payload; only explicitly provided fields are applied."""

    model_config = ConfigDict(extra="forbid")

    name: str | None = None
    slug: str | None = None

    @field_validator("name")
    @classmethod
    def _name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        name = value.strip()
        if not name:
            raise ValueError("name must not be empty")
        if len(name) > MAX_WORKSPACE_NAME:
            raise ValueError(
                f"name must be at most {MAX_WORKSPACE_NAME} characters long"
            )
        return name

    @field_validator("slug")
    @classmethod
    def _slug(cls, value: str | None) -> str | None:
        return None if value is None else _validate_slug(value)


class WorkspaceResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    slug: str
    created_by: uuid.UUID
    my_role: MembershipRole
    created_at: datetime
    updated_at: datetime


class MemberResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    user_id: uuid.UUID
    email: str
    full_name: str | None
    role: MembershipRole
    joined_at: datetime


class RoleUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: MembershipRole


class InvitationCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: EmailAddress
    role: MembershipRole

    @field_validator("role")
    @classmethod
    def _not_owner(cls, value: MembershipRole) -> MembershipRole:
        if value is MembershipRole.OWNER:
            raise ValueError("owner role cannot be granted by invitation")
        return value


class InvitationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    workspace_id: uuid.UUID
    email: str
    role: MembershipRole
    status: InvitationStatus
    expires_at: datetime
    created_at: datetime


class InvitationCreatedResponse(InvitationResponse):
    """Invite result: token/link is shown in the UI instead of sending email."""

    token: str
    accept_url: str


class InvitationAcceptRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    token: str
