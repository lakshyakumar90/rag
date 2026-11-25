"""Add confidence and retrieval_diagnostics columns to messages.

Revision ID: f3a4b5c6d7e8
Revises: e2f3a4b5c6d7
Create Date: 2026-11-25 14:45:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f3a4b5c6d7e8"
down_revision: str | Sequence[str] | None = "e2f3a4b5c6d7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("messages", sa.Column("confidence_score", sa.Float(), nullable=True))
    op.add_column(
        "messages", sa.Column("confidence_level", sa.String(16), nullable=True)
    )
    op.add_column(
        "messages", sa.Column("confidence_breakdown", sa.JSON(), nullable=True)
    )
    op.add_column(
        "messages", sa.Column("retrieval_diagnostics", sa.JSON(), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("messages", "retrieval_diagnostics")
    op.drop_column("messages", "confidence_breakdown")
    op.drop_column("messages", "confidence_level")
    op.drop_column("messages", "confidence_score")
