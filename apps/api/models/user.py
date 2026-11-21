from typing import TYPE_CHECKING

from sqlalchemy import Boolean, CheckConstraint, Index, String, func, true
from sqlalchemy.orm import Mapped, mapped_column, relationship, validates

from models.base import BaseModel

if TYPE_CHECKING:
    from models.document import Document
    from models.membership import Membership
    from models.refresh_token import RefreshToken
    from models.workspace import Workspace


class User(BaseModel):
    __tablename__ = "users"

    email: Mapped[str] = mapped_column(String(320), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    full_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=true()
    )

    refresh_tokens: Mapped[list["RefreshToken"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    memberships: Mapped[list["Membership"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    # RESTRICT at the DB level: a creator cannot be deleted while their
    # workspaces still exist.
    created_workspaces: Mapped[list["Workspace"]] = relationship(
        back_populates="creator", passive_deletes=True
    )
    # RESTRICT prevents deleting a user who uploaded documents.
    uploaded_documents: Mapped[list["Document"]] = relationship(
        back_populates="uploader", passive_deletes=True
    )

    __table_args__ = (
        CheckConstraint("email = lower(email)", name="ck_users_email_lowercase"),
    )

    @validates("email")
    def _normalize_email(self, key: str, value: str) -> str:
        """Store emails in canonical lowercase form on every ORM write."""
        return value.strip().lower()


# Case-insensitive uniqueness, including writes that bypass the ORM validator.
Index("uq_users_email_lower", func.lower(User.__table__.c.email), unique=True)
