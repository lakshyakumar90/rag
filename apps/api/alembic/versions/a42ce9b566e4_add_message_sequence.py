"""add message sequence

Revision ID: a42ce9b566e4
Revises: f5b27650e65e
Create Date: 2026-11-21 22:15:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a42ce9b566e4"
down_revision: str | Sequence[str] | None = "f5b27650e65e"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "messages",
        sa.Column("sequence", sa.Integer(), server_default="0", nullable=False),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("messages", "sequence")
