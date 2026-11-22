"""Persist Settings AI defaults and per-conversation provider/model choices."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "c2d4e6f18a03"
down_revision = "b1a7c9d24e01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "user_ai_defaults",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column("provider", sa.String(100), nullable=False),
        sa.Column("model", sa.String(160), nullable=True),
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
    )
    op.add_column("conversations", sa.Column("provider", sa.String(100), nullable=True))
    op.add_column("conversations", sa.Column("model", sa.String(160), nullable=True))


def downgrade() -> None:
    op.drop_column("conversations", "model")
    op.drop_column("conversations", "provider")
    op.drop_table("user_ai_defaults")
