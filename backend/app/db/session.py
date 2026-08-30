"""Engine and session management.

The unit-of-work boundary is one request, one session, one transaction. The
FastAPI dependency below opens a session per request and always closes it; a
handler that needs a transaction spanning several statements — the Policy
Engine's live re-check followed by the order insert, for instance (ADR-011) —
uses ``session.begin()`` explicitly rather than relying on autocommit
behaviour.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from functools import lru_cache

from sqlalchemy import Engine, create_engine, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from app.config import get_settings

logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def get_engine() -> Engine:
    """Return the process-wide engine, created on first use.

    Creating the engine does not open a connection, so importing this module
    never requires a running database. That matters: the application must be
    importable, and its tests collectable, on a machine with no PostgreSQL.
    """
    settings = get_settings()
    return create_engine(
        settings.database_url,
        echo=settings.db_echo,
        pool_size=settings.db_pool_size,
        pool_pre_ping=True,  # a stale pooled connection fails at checkout, not mid-transaction
        future=True,
        connect_args={"connect_timeout": settings.db_connect_timeout_seconds},
    )


@lru_cache(maxsize=1)
def get_sessionmaker() -> sessionmaker[Session]:
    return sessionmaker(
        bind=get_engine(),
        autoflush=False,
        # Attributes stay loaded after commit, so a response can be serialised
        # from an object the request just committed.
        expire_on_commit=False,
        future=True,
    )


def get_db() -> Iterator[Session]:
    """FastAPI dependency yielding one session per request."""
    session = get_sessionmaker()()
    try:
        yield session
    finally:
        session.close()


def check_database_connection() -> tuple[bool, str | None]:
    """Probe the database for the health endpoint.

    Returns ``(reachable, error_kind)``. ``error_kind`` is the exception class
    name and never the exception message: a psycopg connection error string can
    contain the connection URL, and the URL contains a password.
    """
    try:
        with get_engine().connect() as connection:
            connection.execute(text("SELECT 1"))
    except SQLAlchemyError as exc:  # pragma: no cover - needs a broken database
        logger.warning("database unreachable", extra={"error_kind": type(exc).__name__})
        return False, type(exc).__name__
    return True, None


def reset_engine() -> None:
    """Drop the cached engine and sessionmaker.

    Used by tests that change configuration between cases.
    """
    if get_engine.cache_info().currsize:
        get_engine().dispose()
    get_engine.cache_clear()
    get_sessionmaker.cache_clear()
