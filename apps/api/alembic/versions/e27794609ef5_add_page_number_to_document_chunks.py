"""add page number to document chunks

Revision ID: e27794609ef5
Revises: 800b87a0f86f
Create Date: 2026-11-21 19:15:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e27794609ef5"
down_revision: str | Sequence[str] | None = "800b87a0f86f"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "document_chunks", sa.Column("page_number", sa.Integer(), nullable=True)
    )
    op.create_check_constraint(
        "ck_document_chunks_page_number",
        "document_chunks",
        "page_number IS NULL OR page_number >= 1",
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint(
        "ck_document_chunks_page_number",
        "document_chunks",
        type_="check",
    )
    op.drop_column("document_chunks", "page_number")
