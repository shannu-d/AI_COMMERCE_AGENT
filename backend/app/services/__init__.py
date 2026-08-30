"""Deterministic domain services.

These own business meaning: what a compatible product is, what "in stock" means,
which price is authoritative. They are the trusted side of the trust boundary
(ADR-001) and, by rule, they:

* take an explicit `merchant_id` on every call — never a default, never a value
  read from model output (ADR-002);
* return frozen domain types from `app.domain`, never ORM rows;
* contain no LLM, agent, cart, approval, policy, order or payment logic. M2 is a
  read milestone; those belong to M5 onward.

`app.services` must never import from `app.llm` or `app.agent`.
"""

from app.services.catalog_service import CatalogService
from app.services.compatibility_service import CompatibilityService
from app.services.inventory_service import InventoryService

__all__ = ["CatalogService", "CompatibilityService", "InventoryService"]
