"""Workspace: the top-level container for memberships and invitations."""

import re
import uuid
from typing import TYPE_CHECKING

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship, validates

from models.base import BaseModel

if TYPE_CHECKING:
    from models.document import Document
    from models.invitation import Invitation
    from models.membership import Membership
    from models.user import User

MAX_NAME_LENGTH = 255
MAX_SLUG_LENGTH = 63
_SLUG_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


class Workspace(BaseModel):
    __tablename__ = "workspaces"

    name: Mapped[str] = mapped_column(String(MAX_NAME_LENGTH), nullable=False)
    slug: Mapped[str] = mapped_column(String(MAX_SLUG_LENGTH), nullable=False)
    created_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )

    creator: Mapped["User"] = relationship(
        back_populates="created_workspaces", passive_deletes=True
    )
    memberships: Mapped[list["Membership"]] = relationship(
        back_populates="workspace", cascade="all, delete-orphan"
    )
    invitations: Mapped[list["Invitation"]] = relationship(
        back_populates="workspace", cascade="all, delete-orphan"
    )
    documents: Mapped[list["Document"]] = relationship(
        back_populates="workspace", cascade="all, delete-orphan"
    )

    __table_args__ = (
        UniqueConstraint("slug", name="uq_workspaces_slug"),
        CheckConstraint("slug = lower(slug)", name="ck_workspaces_slug_lowercase"),
    )

    @validates("name")
    def _normalize_name(self, key: str, value: str) -> str:
        if not isinstance(value, str):
            raise ValueError("name must be a string")
        name = value.strip()
        if not name:
            raise ValueError("name is required")
        if len(name) > MAX_NAME_LENGTH:
            raise ValueError(f"name must be at most {MAX_NAME_LENGTH} characters long")
        return name

    @validates("slug")
    def _normalize_slug(self, key: str, value: str) -> str:
        if not isinstance(value, str):
            raise ValueError("slug must be a string")
        slug = value.strip().lower()
        if not slug:
            raise ValueError("slug is required")
        if len(slug) > MAX_SLUG_LENGTH:
            raise ValueError(f"slug must be at most {MAX_SLUG_LENGTH} characters long")
        if not _SLUG_PATTERN.fullmatch(slug):
            raise ValueError(
                "slug must contain only lowercase letters, digits and single hyphens"
            )
        return slug
