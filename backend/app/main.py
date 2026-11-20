"""FastAPI application factory."""

import logging

from fastapi import FastAPI

from app.core.config import get_settings
from app.core.errors import register_error_handlers
from app.core.request_id import RequestIdMiddleware
from app.modules import health


def create_app() -> FastAPI:
    settings = get_settings()
    logging.basicConfig(
        level=settings.log_level,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    app = FastAPI(
        title=f"{settings.brand_name} API",
        # Interactive docs only outside production.
        docs_url=None if settings.is_production else "/api/docs",
        redoc_url=None,
        openapi_url=None if settings.is_production else "/api/openapi.json",
    )
    app.add_middleware(RequestIdMiddleware)
    register_error_handlers(app)
    app.include_router(health.router, prefix="/api")
    return app


app = create_app()
