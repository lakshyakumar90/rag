"""Portable column types: pgvector/tsvector on Postgres, JSON/Text elsewhere.

Tests run against SQLite, which has neither `vector` nor `tsvector`. The
TypeDecorators keep the ORM usable there while emitting the real PG types in
migrations and at runtime against Postgres.
"""

from typing import Any

from pgvector.sqlalchemy import Vector as PGVector
from sqlalchemy import JSON, Text, TypeDecorator
from sqlalchemy.dialects.postgresql import TSVECTOR


class VectorType(TypeDecorator):
    """A fixed-dimension embedding vector (JSON on non-Postgres backends)."""

    impl = JSON
    cache_ok = True

    def __init__(self, dim: int) -> None:
        super().__init__()
        self.dim = dim

    def load_dialect_impl(self, dialect: Any) -> Any:
        if dialect.name == "postgresql":
            return dialect.type_descriptor(PGVector(self.dim))
        return dialect.type_descriptor(JSON())

    def process_bind_param(self, value: Any, dialect: Any) -> Any:
        return value

    def process_result_value(self, value: Any, dialect: Any) -> Any:
        # pgvector may return a list or an array-like; normalize to list[float].
        if value is None or dialect.name != "postgresql":
            return value
        return [float(item) for item in value]


class TSVectorType(TypeDecorator):
    """Full-text search vector (plain Text on non-Postgres backends)."""

    impl = Text
    cache_ok = True

    def load_dialect_impl(self, dialect: Any) -> Any:
        if dialect.name == "postgresql":
            return dialect.type_descriptor(TSVECTOR())
        return dialect.type_descriptor(Text())
