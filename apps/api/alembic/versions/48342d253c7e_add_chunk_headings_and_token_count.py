"""add chunk headings and token count

Revision ID: 48342d253c7e
Revises: e27794609ef5
Create Date: 2026-11-21 20:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "48342d253c7e"
down_revision: str | Sequence[str] | None = "e27794609ef5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "document_chunks", sa.Column("heading_path", sa.JSON(), nullable=True)
    )
    op.add_column(
        "document_chunks",
        sa.Column(
            "token_count",
            sa.Integer(),
            server_default="0",
            nullable=False,
        ),
    )
    op.create_check_constraint(
        "ck_document_chunks_tokens",
        "document_chunks",
        "token_count >= 0",
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint("ck_document_chunks_tokens", "document_chunks", type_="check")
    op.drop_column("document_chunks", "token_count")
    op.drop_column("document_chunks", "heading_path")
