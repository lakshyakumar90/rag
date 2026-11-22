"""Track the active embedding profile per workspace."""

import sqlalchemy as sa
from alembic import op

revision = "f6a8c0e24b17"
down_revision = "e4f6a8b02d35"
branch_labels = None
depends_on = None

DEFAULT_PROFILE = "ollama-embeddinggemma-768-v1"


def upgrade() -> None:
    op.add_column(
        "workspaces",
        sa.Column("active_embedding_profile", sa.String(120), nullable=True),
    )
    op.execute(
        sa.text(
            "UPDATE workspaces SET active_embedding_profile = :profile "
            "WHERE active_embedding_profile IS NULL"
        ).bindparams(profile=DEFAULT_PROFILE)
    )


def downgrade() -> None:
    op.drop_column("workspaces", "active_embedding_profile")
