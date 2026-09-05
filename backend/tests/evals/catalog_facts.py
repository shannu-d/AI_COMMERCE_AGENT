"""The catalogue, as the evaluator is allowed to know it.

**The database is the source of truth and nothing else is.** Every expectation
the graders enforce — this SKU exists, this is its price, this many are on the
shelf, this product fits an iPhone 16 — is read from PostgreSQL through the same
services the application uses, at the moment the suite runs. The case file names
*constraints* ("under 1500", "compatible with iPhone 16", "in stock"); it never
names an answer.

That split is the whole point. A case that hardcoded "AeroCase Pro is 999.00"
would keep passing after a reprice while grading a claim that had become false,
and it would also make the evaluator a second, competing catalogue. Here the
evaluator has no product knowledge of its own: it can only ask the database
whether what the agent said is true.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from decimal import Decimal

from sqlalchemy.orm import Session

from app.domain.catalog import VariantView
from app.domain.inventory import StockStatus, StockView
from app.repositories.variant_repository import VariantQuery
from app.services.catalog_service import CatalogService
from app.services.compatibility_service import CompatibilityService
from app.services.inventory_service import InventoryService
from app.services.recommendation_service import CROSS_SELL_RELATIONSHIP_TYPES

__all__ = ["CatalogFacts", "load_facts", "money"]

_SCALE = Decimal("0.01")


def money(amount: Decimal) -> str:
    """The same fixed-scale string the application emits (ADR-008)."""
    return str(Decimal(amount).quantize(_SCALE))


@dataclass(frozen=True)
class CatalogFacts:
    """Everything the graders may treat as true, read once per run."""

    merchant_id: uuid.UUID
    variants: dict[str, VariantView]
    """SKU -> variant. The only place a price may come from."""
    variants_by_id: dict[uuid.UUID, VariantView]
    stock: dict[uuid.UUID, StockView]
    category_slugs: tuple[str, ...]
    compatible_product_ids: dict[str, frozenset[uuid.UUID]]
    """Canonical target identifier -> the products that genuinely fit it."""
    target_identifiers: tuple[str, ...]
    target_aliases: dict[str, str]
    product_names: dict[uuid.UUID, str]
    #: Source product -> the products the merchant recorded a cross-sell or
    #: bundle relationship to. R15's whole safeguard is that an offer starts
    #: from one of these rows rather than from a search, so the evaluator has to
    #: hold the same table to be able to say an offer was ungrounded.
    related_products: dict[uuid.UUID, frozenset[uuid.UUID]]
    product_id_of_sku: dict[str, uuid.UUID]
    _prices: dict[str, str] = field(default_factory=dict)

    # -- lookups -------------------------------------------------------------

    def price_of(self, sku: str) -> str | None:
        variant = self.variants.get(sku)
        return None if variant is None else money(variant.price)

    def sku_exists(self, sku: str) -> bool:
        return sku in self.variants

    def variant(self, sku: str) -> VariantView | None:
        return self.variants.get(sku)

    def available_quantity(self, sku: str) -> int:
        variant = self.variants.get(sku)
        if variant is None:
            return 0
        view = self.stock.get(variant.id)
        return 0 if view is None else view.available_quantity

    def status_of(self, sku: str) -> StockStatus:
        variant = self.variants.get(sku)
        if variant is None:
            return StockStatus.NO_RECORD
        view = self.stock.get(variant.id)
        return StockStatus.NO_RECORD if view is None else view.status

    def is_compatible(self, sku: str, target_identifier: str) -> bool:
        variant = self.variants.get(sku)
        if variant is None:
            return False
        return variant.product_id in self.compatible_product_ids.get(target_identifier, frozenset())

    def is_related_to(self, sku: str, source_product_id: uuid.UUID) -> bool:
        variant = self.variants.get(sku)
        if variant is None:
            return False
        return variant.product_id in self.related_products.get(source_product_id, frozenset())

    def skus_in_category(self, slug: str) -> tuple[str, ...]:
        return tuple(sku for sku, v in self.variants.items() if v.category_slug == slug)

    def cheapest_in_category(self, slug: str, *, in_stock: bool = True) -> VariantView | None:
        rows = [
            v
            for v in self.variants.values()
            if v.category_slug == slug and (not in_stock or self.available_quantity(v.sku) > 0)
        ]
        return min(rows, key=lambda v: (v.price, v.sku)) if rows else None

    def all_prices(self) -> frozenset[str]:
        """Every price the catalogue actually charges, as strings.

        Used to test prose: a rupee figure the agent quotes that is not in this
        set was not read from the catalogue.
        """
        return frozenset(money(v.price) for v in self.variants.values())


def load_facts(db: Session, merchant_id: uuid.UUID) -> CatalogFacts:
    """Read the whole authoritative picture once.

    Deliberately one snapshot per run rather than a live query per assertion: a
    grader that re-read the database between two checks of one turn could report
    a contradiction that is really just a concurrent write. The drift cases,
    which *want* to see the catalogue move, re-load explicitly.
    """
    catalog = CatalogService(db)
    inventory = InventoryService(db)
    compatibility = CompatibilityService(db)

    variants = catalog.search(merchant_id, VariantQuery(include_inactive=True))
    by_sku = {v.sku: v for v in variants}
    by_id = {v.id: v for v in variants}
    stock = inventory.get_stock_map(merchant_id, [v.id for v in variants])

    targets = compatibility.list_targets()
    compatible: dict[str, frozenset[uuid.UUID]] = {}
    aliases: dict[str, str] = {}
    for target in targets:
        resolution = compatibility.resolve_target(target.canonical_identifier)
        assert resolution.resolved, target.canonical_identifier
        compatible[target.canonical_identifier] = frozenset(
            compatibility.compatible_product_ids(merchant_id, resolution)
        )
        aliases[target.display_name.lower()] = target.canonical_identifier
        for alias in target.aliases:
            aliases[alias.lower()] = target.canonical_identifier

    related: dict[uuid.UUID, frozenset[uuid.UUID]] = {}
    for product_id in {v.product_id for v in variants}:
        rows = catalog.get_related_products(
            merchant_id, product_id, relationship_types=CROSS_SELL_RELATIONSHIP_TYPES
        )
        related[product_id] = frozenset(row.product.id for row in rows)

    return CatalogFacts(
        merchant_id=merchant_id,
        variants=by_sku,
        variants_by_id=by_id,
        stock=stock,
        category_slugs=catalog.category_slugs(merchant_id),
        compatible_product_ids=compatible,
        target_identifiers=tuple(t.canonical_identifier for t in targets),
        target_aliases=aliases,
        product_names={v.product_id: v.product_name for v in variants},
        related_products=related,
        product_id_of_sku={v.sku: v.product_id for v in variants},
    )
