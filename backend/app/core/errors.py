"""Consistent error format: {"error": {"code", "message", "details", "request_id"}}."""

import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = logging.getLogger(__name__)


class AppError(Exception):
    """Base class for expected application errors with a stable machine-readable code."""

    status_code = 400
    code = "bad_request"
    message = "The request could not be processed."

    def __init__(self, message: str | None = None, *, details: Any = None) -> None:
        super().__init__(message or self.message)
        self.message = message or self.message
        self.details = details


class NotFoundError(AppError):
    status_code = 404
    code = "not_found"
    message = "The requested resource was not found."


class AuthenticationError(AppError):
    status_code = 401
    code = "authentication_required"
    message = "Authentication is required."


class PermissionDeniedError(AppError):
    status_code = 403
    code = "permission_denied"
    message = "You do not have permission to perform this action."


class ConflictError(AppError):
    status_code = 409
    code = "conflict"
    message = "The request conflicts with the current state."


class RateLimitError(AppError):
    status_code = 429
    code = "rate_limited"
    message = "Too many requests. Please wait and try again."


class DependencyUnavailableError(AppError):
    status_code = 503
    code = "dependency_unavailable"
    message = "A required service is temporarily unavailable."


_HTTP_CODES = {
    400: "bad_request",
    401: "authentication_required",
    403: "permission_denied",
    404: "not_found",
    405: "method_not_allowed",
    409: "conflict",
    413: "payload_too_large",
    429: "rate_limited",
}


def _request_id(request: Request) -> str | None:
    return getattr(request.state, "request_id", None)


def error_response(
    request: Request, status_code: int, code: str, message: str, details: Any = None
) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={
            "error": {
                "code": code,
                "message": message,
                "details": details,
                "request_id": _request_id(request),
            }
        },
    )


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def handle_app_error(request: Request, exc: AppError) -> JSONResponse:
        return error_response(request, exc.status_code, exc.code, exc.message, exc.details)

    @app.exception_handler(RequestValidationError)
    async def handle_validation(request: Request, exc: RequestValidationError) -> JSONResponse:
        details = [
            {"loc": list(err.get("loc", [])), "msg": err.get("msg"), "type": err.get("type")}
            for err in exc.errors()
        ]
        return error_response(request, 422, "validation_error", "Some fields are invalid.", details)

    @app.exception_handler(StarletteHTTPException)
    async def handle_http(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = _HTTP_CODES.get(exc.status_code, "http_error")
        message = exc.detail if isinstance(exc.detail, str) else "Request failed."
        return error_response(request, exc.status_code, code, message)

    @app.exception_handler(Exception)
    async def handle_unexpected(request: Request, exc: Exception) -> JSONResponse:
        logger.exception("unhandled error (request_id=%s)", _request_id(request))
        return error_response(
            request, 500, "internal_error", "Something went wrong. Please try again."
        )
