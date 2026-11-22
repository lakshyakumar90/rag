"""Optional semantic query cache with a documented similarity threshold."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "a7c9e1b34f56"
down_revision = "f6a8c0e24b17"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "query_cache_entries",
        sa.Column("query_embedding", postgresql.JSON(), nullable=True),
    )
    op.add_column(
        "query_cache_entries",
        sa.Column("embedding_profile", sa.String(120), nullable=True),
    )
    op.execute(
        """
        UPDATE query_cache_entries
           SET embedding_profile = 'ollama-embeddinggemma-768-v1'
         WHERE embedding_profile IS NULL
        """
    )


def downgrade() -> None:
    op.drop_column("query_cache_entries", "embedding_profile")
    op.drop_column("query_cache_entries", "query_embedding")
