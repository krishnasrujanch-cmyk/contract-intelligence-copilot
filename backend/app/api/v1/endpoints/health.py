"""Health check endpoints — used by Docker Compose and Railway.app."""
from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, status
from fastapi.responses import JSONResponse

from app.core.config import settings
from app.infrastructure.database.session import check_database_health

router = APIRouter()


@router.get(
    "",
    summary="Health check",
    response_description="Service health status",
    include_in_schema=True,
)
async def health_check() -> JSONResponse:
    """
    Lightweight health check for load balancers and container orchestrators.
    Verifies connectivity to all dependent services.
    """
    db_ok = await check_database_health()

    overall_healthy = db_ok

    payload = {
        "status": "healthy" if overall_healthy else "degraded",
        "timestamp": datetime.now(UTC).isoformat(),
        "version": settings.app_version,
        "environment": settings.environment.value,
        "services": {
            "database": "ok" if db_ok else "unreachable",
        },
    }

    status_code = (
        status.HTTP_200_OK if overall_healthy else status.HTTP_503_SERVICE_UNAVAILABLE
    )
    return JSONResponse(content=payload, status_code=status_code)
