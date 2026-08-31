"""Fixtures for the M2 service tests.

These run against a **real PostgreSQL**, which the project's documented
development path provides (`docker compose up -d db`). They are marked
`requires_db` and skip only when no database is reachable at all — see
`tests/conftest.py` for that policy and its reason.

The seeded database itself comes from `tests/conftest.py`, because the agent
runtime needs the same catalog and two definitions of "a seeded database" would
be two things to keep in step. What stays here is the service layer built on top
of it.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.orm import Session

from app.identifiers import seed_id
from app.services import CatalogService, CompatibilityService, InventoryService

pytestmark = pytest.mark.requires_db

#: A merchant that is never seeded. Used to prove scoping excludes rather than
#: merely filters — a query that ignored merchant_id would still return rows.
OTHER_MERCHANT_ID = uuid.UUID("00000000-0000-5000-8000-00000000dead")


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
