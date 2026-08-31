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
import uuid
from collections.abc import Iterator

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from app.config import BACKEND_DIR
from app.identifiers import DEFAULT_MERCHANT_ID, seed_id
from app.seed.circuitcraft import seed_catalog
from app.seed.schema import CatalogSeed, load_catalog

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


# --------------------------------------------------------------------------
# A seeded database
#
# Shared rather than per-package: the service tests and the agent runtime need
# the same CircuitCraft catalog, and two definitions of "a seeded database"
# would be two things to keep in step.
#
# It is *ensured* rather than rebuilt - migrate to head if the schema is absent,
# then seed, both idempotent - so these fixtures do not depend on whether another
# module has already migrated, seeded or torn the schema down, and the suite does
# not depend on test ordering.
# --------------------------------------------------------------------------


@pytest.fixture(scope="session")
def catalog_seed() -> CatalogSeed:
    return load_catalog()


@pytest.fixture(scope="module")
def seeded_engine(db_engine: Engine, database_url: str, catalog_seed: CatalogSeed) -> Engine:
    """A database at head with the CircuitCraft catalog loaded.

    Module-scoped rather than wider, and that is load-bearing.
    `tests/db/test_catalog_integrity.py` deliberately downgrades to base at
    its own teardown - proving a fresh database can be built from the
    migrations is the point of that module - so any module running afterwards
    must re-ensure the schema. A session- or package-wide cache would ensure
    it once, before that teardown, and every later module would query a
    database that no longer has tables.
    """
    # Unconditionally, not "if the catalog is missing". Alembic's upgrade is
    # idempotent and a no-op at head, and the earlier check only asked whether
    # *some* schema existed - so a database left at an older revision by another
    # module stayed there, and every test written against a newer table failed
    # with "relation does not exist".
    config = Config(str(BACKEND_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_DIR / "migrations"))
    config.cmd_opts = type("Opts", (), {"x": [f"url={database_url}"]})()  # type: ignore[assignment]
    command.upgrade(config, "head")

    factory = sessionmaker(bind=db_engine, expire_on_commit=False, future=True)
    with factory() as session, session.begin():
        seed_catalog(session, catalog_seed, DEFAULT_MERCHANT_ID)
    return db_engine


@pytest.fixture
def session(seeded_engine: Engine) -> Iterator[Session]:
    """A session whose writes are always rolled back.

    Some tests insert a variant with no inventory row, or a second merchant's
    product, to exercise behaviour the seed deliberately does not contain. None
    of it may survive into the next test.
    """
    factory = sessionmaker(bind=seeded_engine, expire_on_commit=False, future=True)
    with factory() as active:
        yield active
        active.rollback()


@pytest.fixture
def merchant_id() -> uuid.UUID:
    return DEFAULT_MERCHANT_ID


@pytest.fixture
def variant_id():
    """Look up a seeded variant's deterministic id by SKU.

    Seeded rows have deterministic UUIDv5 identifiers (`app/identifiers.py`),
    which is what lets a test name a row without querying for it first.
    """
    return lambda sku: seed_id("variant", sku)


@pytest.fixture
def product_id():
    """Look up a seeded product's deterministic id by slug."""
    return lambda slug: seed_id("product", slug)
