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
from fastapi.middleware.cors import CORSMiddleware

from app import __version__
from app.api.routes import (
    account,
    auth,
    cart,
    catalog,
    chat,
    health,
    merchant,
    orders,
    sessions,
    webhooks,
)
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

    # A browser on the frontend's origin cannot call this API at all without
    # this. Credentials are off deliberately: nothing here reads a cookie or an
    # Authorization header - `session_id` travels in the request body - so there
    # is no ambient authority for a cross-origin page to borrow, and turning
    # credentials on would grant one for no gain (ADR-017).
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_allowed_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
        # Content-Type, plus Authorization for the bearer token ADR-023
        # introduced. Every *other* identifier this API trusts - session_id,
        # cart_version, idempotency_key - still travels in the request body.
        # Note what is still absent: `allow_credentials`. The token is sent
        # explicitly by the client, never attached ambiently by the browser,
        # which is what keeps this API free of CSRF.
        allow_headers=["Content-Type", "Authorization"],
    )

    app.include_router(health.router, prefix="/api")
    app.include_router(auth.router, prefix="/api")
    app.include_router(account.router, prefix="/api")
    app.include_router(catalog.router, prefix="/api")
    app.include_router(chat.router, prefix="/api")
    app.include_router(sessions.router, prefix="/api")
    app.include_router(cart.router, prefix="/api")
    app.include_router(orders.router, prefix="/api")
    app.include_router(webhooks.router, prefix="/api")
    app.include_router(merchant.router, prefix="/api")

    return app


app = create_app()
