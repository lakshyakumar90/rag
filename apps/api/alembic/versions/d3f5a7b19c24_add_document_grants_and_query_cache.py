"""Per-document grants, exact-query cache and embedding profiles.

Existing documents stay unrestricted, so the workspace role remains their
default permission. Restricting a document opts it into the grant allow-list.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "d3f5a7b19c24"
down_revision = "c2d4e6f18a03"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "documents",
        sa.Column(
            "restricted", sa.Boolean(), server_default=sa.false(), nullable=False
        ),
    )
    op.create_table(
        "document_grants",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "document_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("documents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "workspace_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "granted_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "document_id", "user_id", name="uq_document_grants_doc_user"
        ),
    )
    op.create_index(
        "ix_document_grants_workspace_user",
        "document_grants",
        ["workspace_id", "user_id"],
    )

    op.create_table(
        "query_cache_entries",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "workspace_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("cache_key", sa.String(128), nullable=False),
        sa.Column("authorization", sa.String(512), nullable=False),
        sa.Column("response_json", postgresql.JSONB(), nullable=False),
        sa.Column("hit_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint(
            "workspace_id", "cache_key", name="uq_query_cache_workspace_key"
        ),
    )
    op.create_index(
        "ix_query_cache_entries_workspace", "query_cache_entries", ["workspace_id"]
    )

    op.create_table(
        "embedding_profiles",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(120), nullable=False, unique=True),
        sa.Column("provider", sa.String(60), nullable=False),
        sa.Column("model", sa.String(160), nullable=False),
        sa.Column("dimension", sa.Integer(), nullable=False),
        sa.Column("distance", sa.String(20), nullable=False, server_default="'Cosine'"),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("validated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("config_json", postgresql.JSONB(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    # The shipped Ollama profile is enabled so existing installs keep working.
    op.execute(
        """
        INSERT INTO embedding_profiles
            (id, name, provider, model, dimension, distance, version, enabled,
             validated_at, created_at, updated_at)
        VALUES
            (gen_random_uuid(), 'ollama-embeddinggemma-768-v1', 'ollama',
             'embeddinggemma-2:440m', 768, 'Cosine', 1, true, now(), now(), now())
        ON CONFLICT (name) DO NOTHING
        """
    )


def downgrade() -> None:
    op.drop_table("embedding_profiles")
    op.drop_index("ix_query_cache_entries_workspace", table_name="query_cache_entries")
    op.drop_table("query_cache_entries")
    op.drop_index("ix_document_grants_workspace_user", table_name="document_grants")
    op.drop_table("document_grants")
    op.drop_column("documents", "restricted")
