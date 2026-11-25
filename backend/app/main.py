"""FastAPI application factory."""

from fastapi import FastAPI

from app.core.config import get_settings
from app.core.errors import register_error_handlers
from app.core.logs import configure_logging
from app.core.origin_guard import OriginGuardMiddleware
from app.core.request_id import RequestIdMiddleware
from app.modules import health
from app.modules.agent_builder import router as agent_builder
from app.modules.agents import router as agents
from app.modules.conversations import router as conversations
from app.modules.identity import router as identity
from app.modules.workspaces import router as workspaces


def create_app() -> FastAPI:
    settings = get_settings()
    settings.check_production_safety()
    if settings.model_provider == "gemini":
        settings.check_gemini()
    configure_logging(settings.log_level)
    app = FastAPI(
        title=f"{settings.brand_name} API",
        # Interactive docs only outside production.
        docs_url=None if settings.is_production else "/api/docs",
        redoc_url=None,
        # Bodies are read before any throttle runs. Upload routes will need their own limit.
        max_body_size=64 * 1024,
        openapi_url=None if settings.is_production else "/api/openapi.json",
    )
    # Last added is outermost: rejected requests still get a request ID.
    app.add_middleware(OriginGuardMiddleware, allowed_origins=settings.allowed_origins)
    app.add_middleware(RequestIdMiddleware)
    register_error_handlers(app)
    app.include_router(health.router, prefix="/api")
    app.include_router(identity.router, prefix="/api")
    app.include_router(workspaces.router, prefix="/api")
    app.include_router(agents.router, prefix="/api")
    app.include_router(conversations.router, prefix="/api")
    app.include_router(agent_builder.router, prefix="/api")
    return app


app = create_app()
