import logging

from fastapi import FastAPI

from api.v1.router import router as v1_router
from core.logging import configure_logging
from core.middleware import RequestIdMiddleware

logger = logging.getLogger(__name__)


def create_app() -> FastAPI:
    configure_logging()

    app = FastAPI(title="RAG API", version="0.1.0")
    app.add_middleware(RequestIdMiddleware)

    @app.get("/health")
    def health() -> dict[str, str]:
        logger.info("health check")
        return {"status": "ok"}

    app.include_router(v1_router, prefix="/api/v1")
    logger.info("application started")
    return app


app = create_app()
