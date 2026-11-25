"""Add workspace_memories table for 4-tier cognitive memory.

Revision ID: a1b2c3d4e5f6
Revises: f3a4b5c6d7e8
Create Date: 2026-11-25 15:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from models.document import EMBEDDING_DIM
from models.types import VectorType

revision: str = "a1b2c3d4e5f6"
down_revision: str | Sequence[str] | None = "f3a4b5c6d7e8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "workspace_memories",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "workspace_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("tier", sa.String(24), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column(
            "status", sa.String(24), nullable=False, server_default=sa.text("'active'")
        ),
        sa.Column(
            "superseded_by_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("workspace_memories.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "confidence", sa.Float(), nullable=False, server_default=sa.text("0.85")
        ),
        sa.Column("embedding", VectorType(EMBEDDING_DIM), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "tier IN ('semantic', 'episodic', 'procedural')",
            name="ck_workspace_memories_tier",
        ),
        sa.CheckConstraint(
            "status IN ('active', 'superseded')",
            name="ck_workspace_memories_status",
        ),
    )
    op.create_index(
        "ix_workspace_memories_ws_tier_status",
        "workspace_memories",
        ["workspace_id", "tier", "status"],
    )


def downgrade() -> None:
    op.drop_table("workspace_memories")
