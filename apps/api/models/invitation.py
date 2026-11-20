"""Invitation: a token granting a role in a workspace to an email address."""

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship, validates

from models.base import BaseModel
from models.enums import InvitationStatus, MembershipRole, StrEnumType

if TYPE_CHECKING:
    from models.workspace import Workspace

MAX_EMAIL_LENGTH = 320


class Invitation(BaseModel):
    """Only the SHA-256 hash of the invitation token is persisted."""

    __tablename__ = "invitations"

    email: Mapped[str] = mapped_column(
        String(MAX_EMAIL_LENGTH), nullable=False, index=True
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
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    status: Mapped[InvitationStatus] = mapped_column(
        StrEnumType(InvitationStatus),
        nullable=False,
        default=InvitationStatus.PENDING,
        server_default=InvitationStatus.PENDING.value,
    )

    workspace: Mapped["Workspace"] = relationship(back_populates="invitations")

    __table_args__ = (
        UniqueConstraint("token_hash", name="uq_invitations_token_hash"),
        CheckConstraint("email = lower(email)", name="ck_invitations_email_lowercase"),
        CheckConstraint(
            "role IN ('owner', 'admin', 'member')", name="ck_invitations_role"
        ),
        CheckConstraint(
            "status IN ('pending', 'accepted', 'revoked', 'expired')",
            name="ck_invitations_status",
        ),
    )

    @validates("email")
    def _normalize_email(self, key: str, value: str) -> str:
        """Store invitation emails in the same canonical form as user emails."""
        if not isinstance(value, str):
            raise ValueError("email must be a string")
        email = value.strip().lower()
        if not email:
            raise ValueError("email is required")
        if len(email) > MAX_EMAIL_LENGTH:
            raise ValueError(
                f"email must be at most {MAX_EMAIL_LENGTH} characters long"
            )
        return email
