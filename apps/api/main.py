from fastapi import FastAPI

from api.v1.router import router as v1_router


def create_app() -> FastAPI:
    app = FastAPI(title="RAG API", version="0.1.0")

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    app.include_router(v1_router, prefix="/api/v1")
    return app


app = create_app()
