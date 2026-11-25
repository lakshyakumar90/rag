"""Switch document_chunks FTS to multilingual 'simple' config and add pg_trgm index.

Revision ID: d1e2f3a4b5c6
Revises: c9e1f3a57b2d
Create Date: 2026-11-25 14:25:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "d1e2f3a4b5c6"
down_revision: str | Sequence[str] | None = "c9e1f3a57b2d"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    op.execute("DROP INDEX IF EXISTS ix_document_chunks_search_vector")
    op.execute(
        """
        ALTER TABLE document_chunks
        DROP COLUMN IF EXISTS search_vector
        """
    )
    op.execute(
        """
        ALTER TABLE document_chunks
        ADD COLUMN search_vector tsvector
        GENERATED ALWAYS AS (
            to_tsvector(
                'simple',
                coalesce(context_header, '') || ' ' || coalesce(content, '')
            )
        ) STORED
        """
    )
    op.execute(
        """
        CREATE INDEX ix_document_chunks_search_vector
        ON document_chunks USING gin (search_vector)
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_document_chunks_content_trgm
        ON document_chunks USING gin (content gin_trgm_ops)
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_document_chunks_content_trgm")
    op.execute("DROP INDEX IF EXISTS ix_document_chunks_search_vector")
    op.execute("ALTER TABLE document_chunks DROP COLUMN IF EXISTS search_vector")
    op.execute(
        """
        ALTER TABLE document_chunks
        ADD COLUMN search_vector tsvector
        GENERATED ALWAYS AS (to_tsvector('english', content)) STORED
        """
    )
    op.execute(
        """
        CREATE INDEX ix_document_chunks_search_vector
        ON document_chunks USING gin (search_vector)
        """
    )
