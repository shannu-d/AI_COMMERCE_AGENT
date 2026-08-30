"""Domain types returned by the deterministic services.

Services return these, never ORM instances. Three reasons, all of them things
that have bitten this kind of layering before:

* an ORM object carries a live session, so returning one lets a caller lazily
  emit queries from anywhere — including from code that is supposed to be pure;
* an ORM object carries every column, so a tool result built from one leaks
  internal fields the agent has no business seeing (architecture.md A§33);
* these are frozen, so nothing downstream can mutate what it was handed and
  call the result authoritative.

Money is always a ``Decimal`` and always travels next to its currency
(ADR-008).
"""

from app.domain.catalog import (
    CategoryView,
    ProductDetail,
    ProductSummary,
    RelatedProduct,
    VariantView,
)
from app.domain.compatibility import (
    CompatibilityTargetView,
    ResolutionFailure,
    ResolvedTarget,
    TargetResolution,
    UnresolvedTarget,
)
from app.domain.inventory import AvailabilityCheck, StockStatus, StockView

__all__ = [
    "AvailabilityCheck",
    "CategoryView",
    "CompatibilityTargetView",
    "ProductDetail",
    "ProductSummary",
    "RelatedProduct",
    "ResolutionFailure",
    "ResolvedTarget",
    "StockStatus",
    "StockView",
    "TargetResolution",
    "UnresolvedTarget",
    "VariantView",
]
