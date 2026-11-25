"""4-tier cognitive memory ORM model (Semantic, Episodic, Procedural)."""

import uuid

from sqlalchemy import (
    CheckConstraint,
    Float,
    ForeignKey,
    Index,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from models.base import BaseModel
from models.document import EMBEDDING_DIM
from models.types import VectorType


class WorkspaceMemory(BaseModel):
    __tablename__ = "workspace_memories"

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    tier: Mapped[str] = mapped_column(String(24), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(
        String(24), nullable=False, default="active", server_default=text("'active'")
    )
    superseded_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workspace_memories.id", ondelete="SET NULL"),
        nullable=True,
    )
    confidence: Mapped[float] = mapped_column(
        Float, nullable=False, default=0.85, server_default=text("0.85")
    )
    embedding: Mapped[list[float] | None] = mapped_column(
        VectorType(EMBEDDING_DIM), nullable=True
    )

    __table_args__ = (
        CheckConstraint(
            "tier IN ('semantic', 'episodic', 'procedural')",
            name="ck_workspace_memories_tier",
        ),
        CheckConstraint(
            "status IN ('active', 'superseded')",
            name="ck_workspace_memories_status",
        ),
        Index(
            "ix_workspace_memories_ws_tier_status",
            "workspace_id",
            "tier",
            "status",
        ),
    )
