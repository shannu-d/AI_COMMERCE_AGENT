"""FastAPI application factory.

    uvicorn app.main:app --reload

The application starts without a database. That is deliberate: a developer who
has not yet run ``docker compose up -d db`` should get a running server and a
health endpoint that tells them what is missing, rather than a stack trace at
import time.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app import __version__
from app.api.routes import chat, health
from app.config import get_settings
from app.logging_config import configure_logging

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    configure_logging(
        level=settings.log_level,
        fmt=settings.log_format,
        secrets=settings.secret_values(),
    )
    logger.info(
        "application starting",
        extra={
            "environment": settings.environment,
            "version": __version__,
            "merchant_id": str(settings.default_merchant_id),
        },
    )
    yield
    logger.info("application stopping")


def create_app() -> FastAPI:
    settings = get_settings()

    app = FastAPI(
        title=settings.app_name,
        version=__version__,
        description=(
            "Conversational commerce agent for a merchant catalog.\n\n"
            "LLM proposes -> application validates -> user authorizes -> "
            "Razorpay executes -> system audits."
        ),
        lifespan=lifespan,
        # Interactive docs are useful locally and are noise-plus-surface in
        # production.
        docs_url=None if settings.is_production else "/docs",
        redoc_url=None,
        openapi_url=None if settings.is_production else "/openapi.json",
    )

    app.include_router(health.router, prefix="/api")
    app.include_router(chat.router, prefix="/api")

    # Routers added by later milestones, each behind its ADR:
    #   cart     M7
    #   orders   M10  ADR-011
    #   webhooks M12  ADR-012

    return app


app = create_app()
