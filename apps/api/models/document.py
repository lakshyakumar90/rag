"""Document metadata and chunks (embeddings come in a later phase)."""

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import (
    JSON,
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship, validates

from models.base import BaseModel
from models.enums import DocumentStatus, StrEnumType

if TYPE_CHECKING:
    from models.user import User
    from models.workspace import Workspace

MAX_FILENAME_LENGTH = 255
MAX_SHA256_LENGTH = 64
MAX_STORAGE_KEY_LENGTH = 512
MAX_ERROR_LENGTH = 2000

_status_enum = StrEnumType(DocumentStatus)


class Document(BaseModel):
    __tablename__ = "documents"

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    uploaded_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    filename: Mapped[str] = mapped_column(String(MAX_FILENAME_LENGTH), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(100), nullable=False)
    size: Mapped[int] = mapped_column(Integer, nullable=False)
    sha256: Mapped[str] = mapped_column(String(MAX_SHA256_LENGTH), nullable=False)
    storage_key: Mapped[str] = mapped_column(
        String(MAX_STORAGE_KEY_LENGTH), nullable=False
    )
    status: Mapped[DocumentStatus] = mapped_column(
        _status_enum,
        nullable=False,
        default=DocumentStatus.PENDING,
        server_default=DocumentStatus.PENDING.value,
    )
    error: Mapped[str | None] = mapped_column(String(MAX_ERROR_LENGTH), nullable=True)
    page_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Embedding provenance (global settings for v1).
    embedding_model: Mapped[str | None] = mapped_column(String(100), nullable=True)
    embedding_dim: Mapped[int | None] = mapped_column(Integer, nullable=True)

    uploader: Mapped["User"] = relationship(back_populates="uploaded_documents")
    workspace: Mapped["Workspace"] = relationship(back_populates="documents")
    chunks: Mapped[list["DocumentChunk"]] = relationship(
        back_populates="document", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("ix_documents_workspace_sha256", "workspace_id", "sha256"),
        UniqueConstraint(
            "workspace_id", "storage_key", name="uq_documents_storage_key"
        ),
        CheckConstraint("size >= 0", name="ck_documents_size_nonnegative"),
        CheckConstraint(
            "status IN ('pending', 'processing', 'ready', 'failed')",
            name="ck_documents_status",
        ),
    )

    @validates("filename")
    def _validate_filename(self, key: str, value: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValueError("filename is required")
        return value


class DocumentChunk(BaseModel):
    """Text chunk belonging to a document; removed with it via ON DELETE CASCADE."""

    __tablename__ = "document_chunks"

    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("documents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    # None for formats without real pages (TXT/MD/DOCX).
    page_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    # Ordered headings, e.g. ["Guide", "Install"]; null for unheaded formats.
    heading_path: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    token_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    # v1 stores vectors as JSON; a pgvector column/index comes with retrieval.
    embedding: Mapped[list[float] | None] = mapped_column(JSON, nullable=True)

    document: Mapped["Document"] = relationship(back_populates="chunks")

    __table_args__ = (
        UniqueConstraint(
            "document_id", "chunk_index", name="uq_document_chunks_doc_index"
        ),
        CheckConstraint("chunk_index >= 0", name="ck_document_chunks_index"),
        CheckConstraint("token_count >= 0", name="ck_document_chunks_tokens"),
        CheckConstraint(
            "page_number IS NULL OR page_number >= 1",
            name="ck_document_chunks_page_number",
        ),
    )
