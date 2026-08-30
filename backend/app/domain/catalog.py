"""Catalog domain types.

The variant is the sellable unit (architecture.md D§8, D§10; ADR-002), so
``VariantView`` is what searches return — one row per variant, carrying its
parent product's identity (ADR-009, closing open question B7). A row keyed by
product would have no single price.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any


@dataclass(frozen=True, slots=True)
class CategoryView:
    """A category, as the search tool's enumerated vocabulary sees it.

    ``slug`` is what the agent's ``search_catalog`` tool is constrained to
    choose from, so the model cannot name a category that does not exist
    (ADR-009, closing open question B2).
    """

    id: uuid.UUID
    slug: str
    name: str
    parent_slug: str | None = None


@dataclass(frozen=True, slots=True)
class ProductSummary:
    """Product identity, without its variants."""

    id: uuid.UUID
    slug: str
    name: str
    category_slug: str
    brand: str | None = None
    description: str | None = None
    attributes: dict[str, Any] = field(default_factory=dict)
    tags: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class VariantView:
    """The sellable unit: SKU, price and currency, with its parent's identity.

    Every value here comes from PostgreSQL. Nothing on this object may be
    supplied by, adjusted by, or inferred from the model (ADR-001, ADR-002).
    """

    id: uuid.UUID
    sku: str
    name: str
    price: Decimal
    currency: str
    product_id: uuid.UUID
    product_slug: str
    product_name: str
    category_slug: str
    brand: str | None = None
    attributes: dict[str, Any] = field(default_factory=dict)
    product_attributes: dict[str, Any] = field(default_factory=dict)
    tags: tuple[str, ...] = ()

    @property
    def merged_attributes(self) -> dict[str, Any]:
        """Product attributes overlaid with the variant's own.

        The variant wins on conflict: product attributes describe the product,
        variant attributes differentiate the sellable versions (D§27). This is
        the view the M3 preference and relevance scorers will match against.
        """
        return {**self.product_attributes, **self.attributes}


@dataclass(frozen=True, slots=True)
class ProductDetail:
    """A product together with every variant of it."""

    product: ProductSummary
    variants: tuple[VariantView, ...]


@dataclass(frozen=True, slots=True)
class RelatedProduct:
    """A cross-sell, bundle or related-product candidate (D§16, D§17).

    A *candidate*, never a recommendation: R§15 requires cross-sell suggestions
    to be grounded in compatibility and availability, so the caller still filters
    these before offering any of them.
    """

    product: ProductSummary
    relationship_type: str
    priority: int
