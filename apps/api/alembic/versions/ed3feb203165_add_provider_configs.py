"""add provider configs

Revision ID: ed3feb203165
Revises: 65223e6f8aab
Create Date: 2026-11-21 21:45:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "ed3feb203165"
down_revision: str | Sequence[str] | None = "65223e6f8aab"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "provider_configs",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
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
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("provider_type", sa.String(length=50), nullable=False),
        sa.Column("base_url", sa.String(length=512), nullable=True),
        sa.Column("model", sa.String(length=100), nullable=True),
        sa.Column("encrypted_api_key", sa.Text(), nullable=False),
        sa.Column("key_last4", sa.String(length=4), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_provider_configs_user_id"), "provider_configs", ["user_id"]
    )
    op.create_index(
        "ix_provider_configs_user_provider",
        "provider_configs",
        ["user_id", "provider_type"],
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_provider_configs_user_provider", table_name="provider_configs")
    op.drop_index(op.f("ix_provider_configs_user_id"), table_name="provider_configs")
    op.drop_table("provider_configs")
