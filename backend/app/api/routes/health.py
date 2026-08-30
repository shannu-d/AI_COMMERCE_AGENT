"""Health endpoint.

Reports liveness and, separately, whether the database is reachable. The two are
distinguished on purpose: the application being up and the catalog being
available are different facts, and conflating them makes an outage harder to
diagnose.

The response is deliberately thin. It carries no connection string, no
credential, no host name and no exception message — a health endpoint is
usually unauthenticated, and ``check_database_connection`` returns only an
exception *class* name for the same reason.
"""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Response, status
from pydantic import BaseModel, Field

from app import __version__
from app.config import get_settings
from app.db.session import check_database_connection

router = APIRouter(tags=["health"])


class DatabaseHealth(BaseModel):
    configured: bool = Field(description="A database URL is present in configuration.")
    reachable: bool = Field(description="A trivial query succeeded just now.")
    error_kind: str | None = Field(
        default=None,
        description="Exception class name when unreachable. Never a message, never a URL.",
    )


class HealthResponse(BaseModel):
    status: Literal["ok", "degraded"]
    app: str
    version: str
    environment: str
    database: DatabaseHealth


@router.get(
    "/health",
    response_model=HealthResponse,
    summary="Liveness and database reachability",
)
def health(response: Response) -> HealthResponse:
    settings = get_settings()
    reachable, error_kind = check_database_connection()

    if not reachable:
        # The process is alive but cannot serve catalog traffic. 503 lets a
        # readiness probe distinguish that from a healthy instance.
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE

    return HealthResponse(
        status="ok" if reachable else "degraded",
        app=settings.app_name,
        version=__version__,
        environment=settings.environment,
        database=DatabaseHealth(
            configured=bool(settings.database_url),
            reachable=reachable,
            error_kind=error_kind,
        ),
    )
