"""add estimated token flag

Revision ID: aa7a9853ef45
Revises: a42ce9b566e4
Create Date: 2026-11-21 22:30:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "aa7a9853ef45"
down_revision: str | Sequence[str] | None = "a42ce9b566e4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "messages",
        sa.Column(
            "tokens_estimated",
            sa.Boolean(),
            server_default=sa.false(),
            nullable=False,
        ),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("messages", "tokens_estimated")
