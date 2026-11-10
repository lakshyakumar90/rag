from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # Postgres
    postgres_user: str = Field(default="rag", validation_alias="POSTGRES_USER")
    postgres_password: str = Field(default="rag", validation_alias="POSTGRES_PASSWORD")
    postgres_db: str = Field(default="rag", validation_alias="POSTGRES_DB")
    postgres_host: str = Field(default="localhost", validation_alias="POSTGRES_HOST")
    postgres_port: int = Field(default=5432, validation_alias="POSTGRES_PORT")

    # Redis
    redis_host: str = Field(default="localhost", validation_alias="REDIS_HOST")
    redis_port: int = Field(default=6379, validation_alias="REDIS_PORT")

    # MinIO / S3-compatible storage
    minio_root_user: str = Field(
        default="minioadmin", validation_alias="MINIO_ROOT_USER"
    )
    minio_root_password: str = Field(
        default="minioadmin", validation_alias="MINIO_ROOT_PASSWORD"
    )
    minio_host: str = Field(default="localhost", validation_alias="MINIO_HOST")
    minio_port: int = Field(default=9000, validation_alias="MINIO_PORT")
    minio_console_port: int = Field(
        default=9001, validation_alias="MINIO_CONSOLE_PORT"
    )
    minio_bucket: str = Field(default="rag", validation_alias="MINIO_BUCKET")
    minio_secure: bool = Field(default=False, validation_alias="MINIO_SECURE")

    # Ollama / embeddings
    ollama_base_url: str = Field(
        default="http://localhost:11434", validation_alias="OLLAMA_BASE_URL"
    )
    ollama_port: int = Field(default=11434, validation_alias="OLLAMA_PORT")
    ollama_embedding_model: str = Field(
        default="embeddinggemma-2:440m",
        validation_alias="OLLAMA_EMBEDDING_MODEL",
    )

    # App / RAG
    database_url: str | None = Field(default=None, validation_alias="DATABASE_URL")
    api_key: str | None = Field(default=None, validation_alias="API_KEY")

    # CORS (comma-separated origins, e.g. "http://localhost:3000,https://app.example.com")
    cors_origins: str = Field(default="", validation_alias="CORS_ORIGINS")
    cors_allow_credentials: bool = Field(
        default=False, validation_alias="CORS_ALLOW_CREDENTIALS"
    )

    # CLI mode (local only, off by default, enabled via env flag)
    cli_mode_enabled: bool = Field(
        default=False, validation_alias="CLI_MODE_ENABLED"
    )

    @property
    def sqlalchemy_database_url(self) -> str:
        if self.database_url:
            return self.database_url
        return (
            f"postgresql+psycopg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @property
    def redis_url(self) -> str:
        return f"redis://{self.redis_host}:{self.redis_port}/0"

    @property
    def cors_origin_list(self) -> list[str]:
        """CORS_ORIGINS as a trimmed list; empty when unset."""
        return [
            origin.strip() for origin in self.cors_origins.split(",") if origin.strip()
        ]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
