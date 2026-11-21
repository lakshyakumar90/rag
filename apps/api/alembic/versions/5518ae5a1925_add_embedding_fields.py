"""add embedding fields

Revision ID: 5518ae5a1925
Revises: 48342d253c7e
Create Date: 2026-11-21 20:45:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "5518ae5a1925"
down_revision: str | Sequence[str] | None = "48342d253c7e"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "documents", sa.Column("embedding_model", sa.String(100), nullable=True)
    )
    op.add_column("documents", sa.Column("embedding_dim", sa.Integer(), nullable=True))
    op.add_column("document_chunks", sa.Column("embedding", sa.JSON(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("document_chunks", "embedding")
    op.drop_column("documents", "embedding_dim")
    op.drop_column("documents", "embedding_model")
