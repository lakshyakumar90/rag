"""Provenance fields for URL, GitHub and Notion exports."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "b8d0e2f14a6c"
down_revision = "a7c9e1b34f56"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("documents", sa.Column("source_type", sa.String(30), nullable=True))
    op.add_column("documents", sa.Column("source_url", sa.String(2048), nullable=True))
    op.add_column(
        "documents", sa.Column("source_metadata", postgresql.JSON(), nullable=True)
    )
    op.execute("UPDATE documents SET source_type = 'upload' WHERE source_type IS NULL")
    # Multilingual profile: same model family, distinct id (and therefore a
    # distinct Qdrant collection) for evaluated cross-language retrieval.
    op.execute(
        """
        INSERT INTO embedding_profiles
            (id, name, provider, model, dimension, distance, version, enabled,
             created_at, updated_at)
        VALUES
            (gen_random_uuid(), 'multilingual-embeddinggemma-768-v1', 'ollama',
             'embeddinggemma-2:440m', 768, 'Cosine', 1, false, now(), now())
        ON CONFLICT (name) DO NOTHING
        """
    )


def downgrade() -> None:
    op.drop_column("documents", "source_metadata")
    op.drop_column("documents", "source_url")
    op.drop_column("documents", "source_type")
