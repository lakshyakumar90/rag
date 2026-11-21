"""Track document ingestion stages and embedding progress."""

import sqlalchemy as sa
from alembic import op

revision = "e907b6498a10"
down_revision = "9ee0fb955a5b"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "documents", sa.Column("ingestion_stage", sa.String(16), nullable=True)
    )
    op.add_column(
        "documents",
        sa.Column("chunks_embedded", sa.Integer(), server_default="0", nullable=False),
    )


def downgrade() -> None:
    op.drop_column("documents", "chunks_embedded")
    op.drop_column("documents", "ingestion_stage")
