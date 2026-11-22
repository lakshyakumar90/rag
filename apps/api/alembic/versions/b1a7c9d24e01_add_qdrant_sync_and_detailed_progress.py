"""Add Qdrant sync state and detailed, persistent ingestion progress.

Postgres remains the source of truth: these columns record what the worker has
actually done so the UI can show honest progress after a reload, and the sync
table makes the Qdrant backfill resumable and safe to rerun.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "b1a7c9d24e01"
down_revision = "e907b6498a10"
branch_labels = None
depends_on = None

PROGRESS_COLUMNS = (
    "upload_bytes",
    "upload_total",
    "pages_done",
    "ocr_pages_done",
    "sections_done",
    "chunks_embedded",
    "chunks_total",
    "chunks_done",
    "chunks_indexed",
)


def upgrade() -> None:
    op.alter_column(
        "documents", "ingestion_stage", existing_type=sa.String(16), type_=sa.String(24)
    )
    for name in PROGRESS_COLUMNS:
        # chunks_embedded was added by the previous revision; chunks_total and
        # chunks_done come from the vector/search-index revision.
        if name in {"chunks_embedded", "chunks_total", "chunks_done"}:
            continue
        op.add_column(
            "documents",
            sa.Column(name, sa.Integer(), server_default="0", nullable=False),
        )
    for name in ("pages_total", "ocr_pages_total", "sections_total"):
        op.add_column("documents", sa.Column(name, sa.Integer(), nullable=True))
    op.add_column(
        "documents", sa.Column("unreadable_pages", postgresql.JSON(), nullable=True)
    )
    for name in ("progress_updated_at", "qdrant_synced_at"):
        op.add_column(
            "documents", sa.Column(name, sa.DateTime(timezone=True), nullable=True)
        )
    op.add_column(
        "documents", sa.Column("embedding_profile", sa.String(120), nullable=True)
    )
    op.add_column(
        "documents",
        sa.Column("index_version", sa.Integer(), server_default="0", nullable=False),
    )

    # One checkpoint per (document, profile) makes a backfill resumable and
    # lets a re-index bump index_version without touching old points until the
    # replacement is fully written.
    op.create_table(
        "qdrant_sync_state",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "document_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("documents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("embedding_profile", sa.String(120), nullable=False),
        sa.Column("index_version", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("chunks_written", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("chunks_total", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("error", sa.String(1000), nullable=True),
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
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_qdrant_sync_state_document_profile",
        "qdrant_sync_state",
        ["document_id", "embedding_profile"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_qdrant_sync_state_document_profile", table_name="qdrant_sync_state"
    )
    op.drop_table("qdrant_sync_state")
    op.drop_column("documents", "index_version")
    op.drop_column("documents", "embedding_profile")
    op.drop_column("documents", "qdrant_synced_at")
    op.drop_column("documents", "progress_updated_at")
    op.drop_column("documents", "unreadable_pages")
    op.drop_column("documents", "sections_total")
    op.drop_column("documents", "ocr_pages_total")
    op.drop_column("documents", "pages_total")
    for name in reversed(PROGRESS_COLUMNS):
        if name in {"chunks_embedded", "chunks_total", "chunks_done"}:
            continue
        op.drop_column("documents", name)
    op.alter_column(
        "documents", "ingestion_stage", existing_type=sa.String(24), type_=sa.String(16)
    )
