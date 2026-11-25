"""Add parent_content and context_header to document_chunks.

Revision ID: c9e1f3a57b2d
Revises: b8d0e2f14a6c
Create Date: 2026-11-25 14:15:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c9e1f3a57b2d"
down_revision: str | Sequence[str] | None = "b8d0e2f14a6c"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "document_chunks", sa.Column("parent_content", sa.Text(), nullable=True)
    )
    op.add_column(
        "document_chunks", sa.Column("context_header", sa.Text(), nullable=True)
    )
    op.add_column(
        "document_chunks", sa.Column("char_start", sa.Integer(), nullable=True)
    )
    op.add_column(
        "document_chunks", sa.Column("char_end", sa.Integer(), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("document_chunks", "char_end")
    op.drop_column("document_chunks", "char_start")
    op.drop_column("document_chunks", "context_header")
    op.drop_column("document_chunks", "parent_content")
