"""Liveness and readiness endpoints."""

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app.core import database

router = APIRouter(prefix="/health", tags=["health"])


@router.get("")
def liveness() -> dict[str, str]:
    """The process is up. Does not touch dependencies."""
    return {"status": "ok"}


@router.get("/ready")
def readiness() -> JSONResponse:
    """Dependencies are reachable. 503 when any required dependency is not ready."""
    db_status = database.check_database()
    ready = db_status == "ok"
    return JSONResponse(
        status_code=200 if ready else 503,
        content={
            "status": "ready" if ready else "not_ready",
            "checks": {"database": db_status},
        },
    )
