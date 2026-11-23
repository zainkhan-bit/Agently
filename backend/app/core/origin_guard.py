"""CSRF defence: state-changing requests must come from an allowlisted origin."""

from collections.abc import Iterable

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp

from app.core.errors import error_response

_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


class OriginGuardMiddleware(BaseHTTPMiddleware):
    """Reject unsafe methods unless exactly one Origin header matches the allowlist."""

    def __init__(self, app: ASGIApp, allowed_origins: Iterable[str]) -> None:
        super().__init__(app)
        self._allowed = frozenset(allowed_origins) - {"null"}

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        if request.method not in _SAFE_METHODS:
            origins = request.headers.getlist("origin")
            if len(origins) != 1 or origins[0] not in self._allowed:
                return error_response(
                    request, 403, "origin_rejected", "This request's origin is not allowed."
                )
        return await call_next(request)
