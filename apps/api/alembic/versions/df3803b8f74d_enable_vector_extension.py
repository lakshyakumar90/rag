"""enable vector extension

Revision ID: df3803b8f74d
Revises:
Create Date: 2026-11-10 16:37:15.576384

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "df3803b8f74d"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    # pgvector: required for the vector columns / vector indexes used by
    # the retrieval store. The pgvector/pgvector image ships the binaries;
    # this makes the extension available in the database.
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")


def downgrade() -> None:
    """Downgrade schema."""
    # Fails if any vector columns/indexes still exist — drop those objects
    # in a later migration before rolling this back.
    op.execute("DROP EXTENSION IF EXISTS vector")
