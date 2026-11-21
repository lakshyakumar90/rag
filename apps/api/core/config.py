from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# Repo-root .env (shared with docker compose). A .env in the current working
# directory takes precedence when both exist.
_REPO_ROOT_ENV = Path(__file__).resolve().parents[3] / ".env"


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=(_REPO_ROOT_ENV, ".env"),
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
    minio_console_port: int = Field(default=9001, validation_alias="MINIO_CONSOLE_PORT")
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

    # JWT / auth. The secret default is for local development only — override
    # JWT_SECRET_KEY with a random value in any shared environment.
    jwt_secret_key: str = Field(
        default="dev-only-jwt-secret-change-me-in-non-production",
        validation_alias="JWT_SECRET_KEY",
    )
    jwt_algorithm: str = Field(default="HS256", validation_alias="JWT_ALGORITHM")
    access_token_ttl_minutes: int = Field(
        default=15, validation_alias="ACCESS_TOKEN_TTL_MINUTES"
    )
    refresh_token_ttl_days: int = Field(
        default=7, validation_alias="REFRESH_TOKEN_TTL_DAYS"
    )

    # Login rate limiting (Redis counters, per client IP and per email)
    login_rate_limit_max_attempts: int = Field(
        default=5, validation_alias="LOGIN_RATE_LIMIT_MAX_ATTEMPTS"
    )
    login_rate_limit_window_seconds: int = Field(
        default=300, validation_alias="LOGIN_RATE_LIMIT_WINDOW_SECONDS"
    )
    # Only trust X-Forwarded-For when the app sits behind a trusted proxy.
    trust_proxy_headers: bool = Field(
        default=False, validation_alias="TRUST_PROXY_HEADERS"
    )

    # Refresh-token cookie. HttpOnly is always on; Secure defaults on and can
    # be disabled for local plain-HTTP development.
    refresh_cookie_name: str = Field(
        default="refresh_token", validation_alias="REFRESH_COOKIE_NAME"
    )
    refresh_cookie_path: str = Field(
        default="/api/v1/auth", validation_alias="REFRESH_COOKIE_PATH"
    )
    refresh_cookie_secure: bool = Field(
        default=True, validation_alias="REFRESH_COOKIE_SECURE"
    )
    refresh_cookie_samesite: Literal["lax", "strict", "none"] = Field(
        default="lax", validation_alias="REFRESH_COOKIE_SAMESITE"
    )

    # Invitations. The accept token is returned to the caller because there is
    # no local mail server; the base URL is used to build a clickable link for
    # the UI.
    invitation_ttl_days: int = Field(default=7, validation_alias="INVITATION_TTL_DAYS")
    invitation_accept_base_url: str = Field(
        default="http://localhost:3000/invitations/accept",
        validation_alias="INVITATION_ACCEPT_BASE_URL",
    )

    # Document uploads
    max_upload_size_bytes: int = Field(
        default=25 * 1024 * 1024, validation_alias="MAX_UPLOAD_SIZE_BYTES"
    )
    presigned_url_ttl_seconds: int = Field(
        default=900, validation_alias="PRESIGNED_URL_TTL_SECONDS"
    )

    # Background ingestion worker (ARQ)
    ingest_max_tries: int = Field(default=3, validation_alias="INGEST_MAX_TRIES")
    ingest_retry_backoff_seconds: float = Field(
        default=2.0, validation_alias="INGEST_RETRY_BACKOFF_SECONDS"
    )
    ingest_job_timeout_seconds: float = Field(
        default=300.0, validation_alias="INGEST_JOB_TIMEOUT_SECONDS"
    )
    worker_max_jobs: int = Field(default=10, validation_alias="WORKER_MAX_JOBS")

    # CORS (comma-separated origins, e.g. "http://localhost:3000,https://app.example.com")
    cors_origins: str = Field(default="", validation_alias="CORS_ORIGINS")
    cors_allow_credentials: bool = Field(
        default=False, validation_alias="CORS_ALLOW_CREDENTIALS"
    )

    # CLI mode (local only, off by default, enabled via env flag)
    cli_mode_enabled: bool = Field(default=False, validation_alias="CLI_MODE_ENABLED")

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
