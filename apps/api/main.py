import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.v1.router import router as v1_router
from core.config import get_settings
from core.exceptions import register_exception_handlers
from core.logging import configure_logging
from core.middleware import RequestIdMiddleware

logger = logging.getLogger(__name__)


def create_app() -> FastAPI:
    configure_logging()
    settings = get_settings()

    app = FastAPI(title="RAG API", version="0.1.0")
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
        logger.info("health check")
        return {"status": "ok"}

    app.include_router(v1_router, prefix="/api/v1")
    logger.info("application started")
    return app


app = create_app()
