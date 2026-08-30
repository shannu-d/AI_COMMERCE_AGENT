"""Data access.

The layer architecture.md A§20 names — Runtime → Tool Handler → Service →
Repository → PostgreSQL — and which no file tree in the specification includes.

Repositories own SQL and return ORM rows. Services own business meaning and
return domain types. Keeping the split means a service can be reasoned about
without reading query construction, and a query can be tuned without touching
business rules.

**Every method takes a `merchant_id` and filters on it.** Merchant scoping is a
hard constraint (ADR-002, ADR-005), and a repository that accepts an optional
merchant is a repository that will eventually be called without one.
"""

from app.repositories.compatibility_repository import CompatibilityRepository
from app.repositories.inventory_repository import InventoryRepository
from app.repositories.product_repository import ProductRepository
from app.repositories.variant_repository import VariantRepository

__all__ = [
    "CompatibilityRepository",
    "InventoryRepository",
    "ProductRepository",
    "VariantRepository",
]
