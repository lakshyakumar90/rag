"""Assign the shipped profile to pre-v2 documents so they can be backfilled.

Rows created by v1 have no ``embedding_profile`` value. Their model and
dimension match the shipped Ollama profile, so they are safe to copy into the
default collection without re-embedding.
"""

import sqlalchemy as sa
from alembic import op

revision = "e4f6a8b02d35"
down_revision = "d3f5a7b19c24"
branch_labels = None
depends_on = None

PROFILE = "ollama-embeddinggemma-768-v1"
MODEL = "embeddinggemma-2:440m"


def upgrade() -> None:
    op.execute(
        sa.text(
            """
            UPDATE documents
               SET embedding_profile = :profile
             WHERE embedding_profile IS NULL
               AND status = 'ready'
               AND (embedding_model = :model OR embedding_model IS NULL)
               AND (embedding_dim = 768 OR embedding_dim IS NULL)
            """
        ).bindparams(profile=PROFILE, model=MODEL)
    )


def downgrade() -> None:
    # Profiles are provenance metadata; the vectors themselves are unchanged.
    op.execute(
        sa.text(
            """
            UPDATE documents SET embedding_profile = NULL
             WHERE embedding_profile = :profile
            """
        ).bindparams(profile=PROFILE)
    )
