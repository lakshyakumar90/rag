"""Membership: a user's role in a workspace (unique per user/workspace pair)."""

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, ForeignKey, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from models.base import BaseModel
from models.enums import MembershipRole, StrEnumType

if TYPE_CHECKING:
    from models.user import User
    from models.workspace import Workspace


class Membership(BaseModel):
    __tablename__ = "memberships"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    role: Mapped[MembershipRole] = mapped_column(
        StrEnumType(MembershipRole), nullable=False
    )

    user: Mapped["User"] = relationship(back_populates="memberships")
    workspace: Mapped["Workspace"] = relationship(back_populates="memberships")

    __table_args__ = (
        UniqueConstraint(
            "user_id", "workspace_id", name="uq_memberships_user_workspace"
        ),
        CheckConstraint(
            "role IN ('owner', 'admin', 'member')", name="ck_memberships_role"
        ),
    )
