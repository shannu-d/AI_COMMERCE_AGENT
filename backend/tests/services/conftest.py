"""Fixtures for the M2 service tests.

These run against a **real PostgreSQL**, which the project's documented
development path provides (`docker compose up -d db`). They are marked
`requires_db` and skip only when no database is reachable at all — see
`tests/conftest.py` for that policy and its reason.

The database is *ensured* rather than rebuilt: migrate to head if the schema is
absent, then seed, both idempotent. That makes these fixtures independent of
whether another module has already migrated, seeded, or torn the schema down,
so the suite does not depend on test ordering.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, inspect
from sqlalchemy.orm import Session, sessionmaker

from app.config import BACKEND_DIR
from app.identifiers import DEFAULT_MERCHANT_ID, seed_id
from app.seed.circuitcraft import seed_catalog
from app.seed.schema import CatalogSeed, load_catalog
from app.services import CatalogService, CompatibilityService, InventoryService

pytestmark = pytest.mark.requires_db

#: A merchant that is never seeded. Used to prove scoping excludes rather than
#: merely filters — a query that ignored merchant_id would still return rows.
OTHER_MERCHANT_ID = uuid.UUID("00000000-0000-5000-8000-00000000dead")


@pytest.fixture(scope="package")
def catalog_seed() -> CatalogSeed:
    return load_catalog()


@pytest.fixture(scope="package")
def seeded_engine(db_engine: Engine, database_url: str, catalog_seed: CatalogSeed) -> Engine:
    """A database at head with the CircuitCraft catalog loaded."""
    if "products" not in inspect(db_engine).get_table_names():
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
def catalog(session: Session) -> CatalogService:
    return CatalogService(session)


@pytest.fixture
def compatibility(session: Session) -> CompatibilityService:
    return CompatibilityService(session)


@pytest.fixture
def inventory(session: Session) -> InventoryService:
    return InventoryService(session)


@pytest.fixture
def variant_id():
    """Look up a seeded variant's deterministic id by SKU."""
    return lambda sku: seed_id("variant", sku)


@pytest.fixture
def product_id():
    """Look up a seeded product's deterministic id by slug."""
    return lambda slug: seed_id("product", slug)
