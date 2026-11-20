import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.exc import SQLAlchemyError

from api.v1.router import router as v1_router
from core.config import get_settings
from core.database import check_database_health, dispose_engine
from core.exceptions import register_exception_handlers
from core.logging import configure_logging
from core.middleware import RequestIdMiddleware
from core.redis import close_redis_client

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    await close_redis_client()
    await dispose_engine()


def create_app() -> FastAPI:
    configure_logging()
    settings = get_settings()

    app = FastAPI(title="RAG API", version="0.1.0", lifespan=lifespan)
    app.add_middleware(RequestIdMiddleware)
    if settings.cors_origin_list:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_origin_list,
            allow_credentials=settings.cors_allow_credentials,
            allow_methods=["*"],
            allow_headers=["*"],
        )
        logger.info("CORS enabled for origins: %s", settings.cors_origin_list)
    register_exception_handlers(app)

    @app.get("/health")
    def health() -> dict[str, str]:
        """Liveness probe: the process is up (independent of dependencies)."""
        logger.info("health check")
        return {"status": "ok"}

    @app.get("/health/db")
    async def health_db() -> dict[str, str]:
        """Readiness probe: confirms the database connection works."""
        try:
            await check_database_health()
        except SQLAlchemyError as exc:
            logger.warning("database health check failed: %s", exc)
            raise HTTPException(status_code=503, detail="database unavailable") from exc
        return {"status": "ok", "database": "ok"}

    app.include_router(v1_router, prefix="/api/v1")
    logger.info("application started")
    return app


app = create_app()
