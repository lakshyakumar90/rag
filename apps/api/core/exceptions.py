import logging
from typing import Any, cast

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from core.logging import request_id_ctx

logger = logging.getLogger(__name__)


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
            details=validation_exc.errors(),
        ),
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


def register_exception_handlers(app: FastAPI) -> None:
    app.add_exception_handler(StarletteHTTPException, http_exception_handler)
    app.add_exception_handler(HTTPException, http_exception_handler)
    app.add_exception_handler(RequestValidationError, validation_exception_handler)
    app.add_exception_handler(Exception, unhandled_exception_handler)
