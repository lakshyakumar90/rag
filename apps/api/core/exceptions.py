import logging
from typing import Any, cast

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from psycopg.errors import ConnectionTimeout
from sqlalchemy.exc import OperationalError
from starlette.exceptions import HTTPException as StarletteHTTPException

from core.logging import request_id_ctx

logger = logging.getLogger(__name__)


class DomainError(Exception):
    """Base class for expected failures raised by the service layer.

    Services stay framework-agnostic: they raise these typed errors and the
    HTTP layer translates them into the app's standard error envelope.
    """

    status_code: int = 400
    code: str = "DOMAIN_ERROR"
    message: str = "Request could not be completed"
    headers: dict[str, str] | None = None

    def __init__(self, message: str | None = None, *, details: Any = None) -> None:
        super().__init__(message or self.message)
        self.message = message or self.message
        self.details = details


def _error_payload(
    *,
    code: str,
    message: str,
    request_id: str | None,
    details: Any = None,
) -> dict[str, Any]:
    error: dict[str, Any] = {
        "code": code,
        "message": message,
        "request_id": request_id,
    }
    if details is not None:
        error["details"] = details
    return {"error": error}


def _request_id(request: Request) -> str | None:
    return getattr(request.state, "request_id", None) or request_id_ctx.get()


async def http_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    http_exc = cast(StarletteHTTPException, exc)
    request_id = _request_id(request)
    detail = http_exc.detail
    if isinstance(detail, dict):
        message = str(detail.get("message") or detail.get("detail") or "Request failed")
        details = detail.get("details", detail)
        code = str(detail.get("code") or f"HTTP_{http_exc.status_code}")
    elif isinstance(detail, list):
        message = "Request failed"
        details = detail
        code = f"HTTP_{http_exc.status_code}"
    else:
        message = str(detail) if detail else "Request failed"
        details = None
        code = f"HTTP_{http_exc.status_code}"

    return JSONResponse(
        status_code=http_exc.status_code,
        content=_error_payload(
            code=code,
            message=message,
            request_id=request_id,
            details=details,
        ),
        headers=getattr(http_exc, "headers", None),
    )


def _validation_details(exc: RequestValidationError) -> list[dict[str, Any]]:
    """Make Pydantic errors JSON-safe without echoing submitted values.

    ``errors()`` may carry exception objects in ``ctx`` (not serializable) and
    always includes ``input`` — which would leak passwords back to the client.
    """
    details: list[dict[str, Any]] = []
    for error in exc.errors():
        item: dict[str, Any] = {
            "type": error.get("type"),
            "loc": list(error.get("loc", ())),
            "msg": error.get("msg"),
        }
        ctx = error.get("ctx")
        if ctx:
            item["ctx"] = {key: str(value) for key, value in ctx.items()}
        details.append(item)
    return details


async def validation_exception_handler(
    request: Request, exc: Exception
) -> JSONResponse:
    validation_exc = cast(RequestValidationError, exc)
    request_id = _request_id(request)
    return JSONResponse(
        status_code=422,
        content=_error_payload(
            code="VALIDATION_ERROR",
            message="Request validation failed",
            request_id=request_id,
            details=_validation_details(validation_exc),
        ),
    )


async def domain_error_handler(request: Request, exc: Exception) -> JSONResponse:
    domain_exc = cast(DomainError, exc)
    return JSONResponse(
        status_code=domain_exc.status_code,
        content=_error_payload(
            code=domain_exc.code,
            message=domain_exc.message,
            request_id=_request_id(request),
            details=domain_exc.details,
        ),
        headers=domain_exc.headers,
    )


async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    request_id = _request_id(request)
    logger.exception(
        "unhandled exception",
        extra={"path": request.url.path, "method": request.method},
    )
    return JSONResponse(
        status_code=500,
        content=_error_payload(
            code="INTERNAL_SERVER_ERROR",
            message="An unexpected error occurred",
            request_id=request_id,
        ),
    )


async def database_error_handler(request: Request, exc: Exception) -> JSONResponse:
    error = cast(OperationalError, exc)
    if not error.connection_invalidated and not isinstance(
        error.orig, ConnectionTimeout
    ):
        return await unhandled_exception_handler(request, exc)
    logger.warning("Database connection unavailable", extra={"path": request.url.path})
    return JSONResponse(
        status_code=503,
        headers={"Retry-After": "1"},
        content=_error_payload(
            code="DATABASE_UNAVAILABLE",
            message="The database is temporarily unavailable. Try again shortly.",
            request_id=_request_id(request),
        ),
    )


def register_exception_handlers(app: FastAPI) -> None:
    app.add_exception_handler(StarletteHTTPException, http_exception_handler)
    app.add_exception_handler(HTTPException, http_exception_handler)
    app.add_exception_handler(RequestValidationError, validation_exception_handler)
    app.add_exception_handler(DomainError, domain_error_handler)
    app.add_exception_handler(OperationalError, database_error_handler)
    app.add_exception_handler(Exception, unhandled_exception_handler)
