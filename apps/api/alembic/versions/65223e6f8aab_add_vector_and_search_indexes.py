"""add vector and search indexes

Revision ID: 65223e6f8aab
Revises: 5518ae5a1925
Create Date: 2026-11-21 21:15:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "65223e6f8aab"
down_revision: str | Sequence[str] | None = "5518ae5a1925"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

DIM = 768


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "documents",
        sa.Column("chunks_total", sa.Integer(), server_default="0", nullable=False),
    )
    op.add_column(
        "documents",
        sa.Column("chunks_done", sa.Integer(), server_default="0", nullable=False),
    )

    # Convert the v1 JSON vectors to pgvector; JSON text like [0.1, 0.2] is
    # valid pgvector input.
    op.alter_column(
        "document_chunks",
        "embedding",
        type_=Vector(DIM),
        existing_type=sa.JSON(),
        postgresql_using="embedding::text::vector(768)",
    )

    # Generated tsvector: PostgreSQL keeps it in sync with content.
    op.execute(
        """
        ALTER TABLE document_chunks
        ADD COLUMN search_vector tsvector
        GENERATED ALWAYS AS (to_tsvector('english', coalesce(content, ''))) STORED
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_document_chunks_embedding_hnsw
        ON document_chunks USING hnsw (embedding vector_cosine_ops)
        WHERE embedding IS NOT NULL
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_document_chunks_search_gin
        ON document_chunks USING gin (search_vector)
        """
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("DROP INDEX IF EXISTS ix_document_chunks_search_gin")
    op.execute("DROP INDEX IF EXISTS ix_document_chunks_embedding_hnsw")
    op.drop_column("document_chunks", "search_vector")
    op.alter_column(
        "document_chunks",
        "embedding",
        type_=postgresql.JSON(),
        existing_type=Vector(DIM),
        postgresql_using="embedding::text::json",
    )
    op.drop_column("documents", "chunks_done")
    op.drop_column("documents", "chunks_total")
