"""Shared test fixtures.

The important policy in this file is how the suite behaves without a database.

ADR-002 forbids substituting a different engine for tests, and this machine may
have no PostgreSQL at all. So tests that genuinely need a server are marked
``requires_db`` and are **skipped with a visible reason** when none is
reachable. They are never quietly passed, and they are never redirected at a
weaker engine that would make them pass for the wrong reason.

Everything that can be verified without a server — schema metadata, the
PostgreSQL DDL the migrations compile to, seed-data integrity, configuration,
the application boot and its health endpoint — runs unconditionally.
"""

from __future__ import annotations

import os
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.exc import SQLAlchemyError

# Tests must never touch the development database or read a developer's .env.
os.environ["ENVIRONMENT"] = "test"

_DB_SKIP_REASON = (
    "No reachable PostgreSQL. Set TEST_DATABASE_URL, or run "
    "`docker compose up -d db` from the repository root. "
    "ADR-002: tests are never redirected to a different engine."
)


def _test_database_url() -> str | None:
    return os.environ.get("TEST_DATABASE_URL")


def _database_is_reachable(url: str) -> bool:
    try:
        engine = create_engine(url, connect_args={"connect_timeout": 3})
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        engine.dispose()
    except SQLAlchemyError:
        return False
    return True


@pytest.fixture(scope="session")
def database_url() -> str:
    """URL of a reachable test database, or skip."""
    url = _test_database_url()
    if not url or not _database_is_reachable(url):
        pytest.skip(_DB_SKIP_REASON)
    return url


@pytest.fixture(scope="session")
def db_engine(database_url: str) -> Iterator[Engine]:
    engine = create_engine(database_url, future=True)
    yield engine
    engine.dispose()


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """Skip ``requires_db`` tests up front, once, with one reason.

    Probing once at collection time keeps the run fast and makes the skip
    reason appear in the summary rather than being repeated per test.
    """
    url = _test_database_url()
    if url and _database_is_reachable(url):
        return

    skip = pytest.mark.skip(reason=_DB_SKIP_REASON)
    for item in items:
        if "requires_db" in item.keywords:
            item.add_marker(skip)


@pytest.fixture
def client() -> Iterator[TestClient]:
    """A TestClient with the application lifespan actually run."""
    from app.main import create_app

    with TestClient(create_app()) as test_client:
        yield test_client
