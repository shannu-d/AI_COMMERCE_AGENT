# Bug — Ambiguous Foreign Keys Between Products and Categories Caused Mapper Crash

**Date:** August 30, 2026  
**Time:** 23:28:51 +0530

### Question

Can SQLAlchemy configure its ORM relationships between `Product` and `Category` models without ambiguity when both plain and composite foreign keys exist on the same tables?

### What I Expected

I expected SQLAlchemy to automatically configure relationships between `Product` and `Category` so that accessing `category.products` or `product.category` works reliably in queries.

### What Actually Happened

During our initial live database tests on M1, querying `Category` with relationship access crashed with:
`sqlalchemy.exc.AmbiguousForeignKeysError: Could not determine join condition between parent/child tables on relationship Category.products...`

Because SQLAlchemy configures mappers lazily upon first query execution, this error remained completely hidden during initial schema definition and offline unit testing until a live query was executed.

### Why Was This a Problem?

This crashed any query attempting to join or preload `Category.products`. It was an architectural stumbling block on day one of building the catalog service.

### Root Cause

To enforce strict multi-tenant merchant isolation at the database level (ADR-002), the schema had two foreign keys between `products` and `categories`:
1. `products.category_id -> categories.id` (standard foreign key)
2. `(products.merchant_id, products.category_id) -> categories.(merchant_id, id)` (composite foreign key enforcing that a product's category belongs to the exact same merchant)

Because there were two valid foreign-key paths between the two tables, SQLAlchemy's mapper generator could not guess which column was the intended join condition.

### Decision

We decided to explicitly declare the `foreign_keys` argument on the `Category.products` and `Product.category` relationships, and to add an offline test that explicitly calls `configure_mappers()` so that ambiguous relationships fail during unit testing without needing a database.

### Fix

In commit `bca07c8`:
1. Specified explicit `foreign_keys=[category_id]` on the relationship in `app/db/models/catalog.py`.
2. Created a new offline unit test in `backend/tests/db/test_catalog_schema.py`:
   ```python
   def test_every_orm_relationship_resolves() -> None:
       """Catches ambiguous joins without needing a database."""
       from sqlalchemy.orm import configure_mappers
       configure_mappers()
   ```

### Verification

Ran `pytest tests/db/test_catalog_schema.py`. Mapper configuration succeeded without ambiguity, and live database queries in `tests/db/test_catalog_integrity.py` ran cleanly.

### Result

PASS. All ORM relationships compile and resolve unambiguously.

### Evidence

- Git commit: `bca07c8 fix: resolve two defects that only a live database exposed (M1)`
- Files: [`backend/app/db/models/catalog.py`](file:///l:/AI_COMMERCE/backend/app/db/models/catalog.py), [`backend/tests/db/test_catalog_schema.py`](file:///l:/AI_COMMERCE/backend/tests/db/test_catalog_schema.py)
- Regression test: [`backend/tests/db/test_catalog_schema.py::test_every_orm_relationship_resolves`](file:///l:/AI_COMMERCE/backend/tests/db/test_catalog_schema.py#L360-L373)
