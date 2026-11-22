"""Per-document grants, exact-query cache and embedding profiles."""

import uuid
from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from models.base import BaseModel


class DocumentGrant(BaseModel):
    __tablename__ = "document_grants"

    document_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    workspace_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    granted_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)

    __table_args__ = (
        UniqueConstraint("document_id", "user_id", name="uq_document_grants_doc_user"),
    )


class QueryCacheEntry(BaseModel):
    __tablename__ = "query_cache_entries"

    workspace_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    cache_key: Mapped[str] = mapped_column(String(128), nullable=False)
    authorization: Mapped[str] = mapped_column(String(512), nullable=False)
    response_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    hit_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # JSON keeps the cache usable across profiles with different dimensions.
    query_embedding: Mapped[list[float] | None] = mapped_column(JSON, nullable=True)
    embedding_profile: Mapped[str | None] = mapped_column(String(120), nullable=True)

    __table_args__ = (
        UniqueConstraint(
            "workspace_id", "cache_key", name="uq_query_cache_workspace_key"
        ),
    )


class EmbeddingProfile(BaseModel):
    __tablename__ = "embedding_profiles"

    name: Mapped[str] = mapped_column(String(120), nullable=False, unique=True)
    provider: Mapped[str] = mapped_column(String(60), nullable=False)
    model: Mapped[str] = mapped_column(String(160), nullable=False)
    dimension: Mapped[int] = mapped_column(Integer, nullable=False)
    distance: Mapped[str] = mapped_column(
        String(20), nullable=False, default="Cosine", server_default="Cosine"
    )
    version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default="1"
    )
    enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    validated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    config_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
