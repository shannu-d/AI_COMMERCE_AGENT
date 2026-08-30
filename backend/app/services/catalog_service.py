"""Catalog Service — authoritative product facts.

architecture.md A§21 gives its responsibilities: product retrieval, variant
retrieval, SKU lookup, catalog search, and authoritative price retrieval.

The rule it exists to enforce is the pre-submission gate item quoted in
`docs/notes/external-brief-gap.md` (PG-2): *the agent cannot invent SKUs,
prices, stock, or payment status.* This service is where that stops being a
principle and becomes a lookup. Every value it returns was read from PostgreSQL
in the call that returned it. It has no defaults, no fallbacks and no
construction path for a product, a SKU or a price.

A model-supplied `variant_id` or `sku` is a **lookup key, never a fact**: it is
resolved here, and a miss returns `None` rather than anything invented
(ADR-009).
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Sequence
from decimal import Decimal

from sqlalchemy.orm import Session

from app.domain import CategoryView, ProductDetail, ProductSummary, RelatedProduct, VariantView
from app.repositories import ProductRepository, VariantRepository
from app.repositories.variant_repository import VariantQuery
from app.services._mapping import to_category_view, to_product_summary, to_variant_view

logger = logging.getLogger(__name__)

__all__ = ["CatalogService", "VariantQuery"]


class CatalogService:
    """Reads authoritative catalog data. Never writes, never invents."""

    def __init__(self, session: Session) -> None:
        self._products = ProductRepository(session)
        self._variants = VariantRepository(session)

    # -- products ------------------------------------------------------------

    def get_product(self, merchant_id: uuid.UUID, product_id: uuid.UUID) -> ProductDetail | None:
        """A product with all of its active variants, or `None`."""
        product = self._products.get(merchant_id, product_id)
        if product is None:
            return None
        variants = self._variants.for_products(merchant_id, [product.id])
        return ProductDetail(
            product=to_product_summary(product),
            variants=tuple(to_variant_view(v) for v in variants),
        )

    def get_product_by_slug(self, merchant_id: uuid.UUID, slug: str) -> ProductDetail | None:
        product = self._products.get_by_slug(merchant_id, slug)
        if product is None:
            return None
        return self.get_product(merchant_id, product.id)

    def get_products(
        self, merchant_id: uuid.UUID, product_ids: Sequence[uuid.UUID]
    ) -> list[ProductSummary]:
        return [to_product_summary(p) for p in self._products.get_many(merchant_id, product_ids)]

    # -- variants: the sellable unit ----------------------------------------

    def get_variant(self, merchant_id: uuid.UUID, variant_id: uuid.UUID) -> VariantView | None:
        variant = self._variants.get(merchant_id, variant_id)
        return to_variant_view(variant) if variant else None

    def get_variant_by_sku(self, merchant_id: uuid.UUID, sku: str) -> VariantView | None:
        """SKU lookup. A SKU that does not exist returns `None`.

        This is the check that rejects a fabricated SKU (A§30). It does not
        normalise, correct, or fuzzy-match the input: `UNIQUE(merchant_id, sku)`
        makes the lookup exact, and an approximate match would be a guess about
        what the buyer is purchasing.
        """
        variant = self._variants.get_by_sku(merchant_id, sku)
        return to_variant_view(variant) if variant else None

    def get_variants(
        self, merchant_id: uuid.UUID, variant_ids: Sequence[uuid.UUID]
    ) -> list[VariantView]:
        return [to_variant_view(v) for v in self._variants.get_many(merchant_id, variant_ids)]

    def get_authoritative_price(
        self, merchant_id: uuid.UUID, variant_id: uuid.UUID
    ) -> tuple[Decimal, str] | None:
        """The current price and currency, read live.

        RULE 6 and RULE 12: prices come from the database, and are re-verified
        before checkout because catalog state may have changed. Every caller on
        the money path — the cart when it refreshes, the Policy Engine before
        order creation (ADR-011, ADR-014) — reads through here rather than
        trusting a value it was handed.

        Returns `(Decimal, currency)`, never a float (ADR-008).
        """
        variant = self._variants.get(merchant_id, variant_id)
        if variant is None:
            return None
        return variant.price, variant.currency

    # -- search --------------------------------------------------------------

    def search(self, merchant_id: uuid.UUID, query: VariantQuery) -> list[VariantView]:
        """Catalog search: one row per variant, deterministically ordered.

        Applies the catalog's own filters — category, budget, text, attributes —
        and **not** compatibility or inventory. Those are separate hard
        constraints owned by their own services (ADR-005); M3's filter composes
        all three in the order D§29 sets out.
        """
        return [to_variant_view(v) for v in self._variants.search(merchant_id, query)]

    # -- categories ----------------------------------------------------------

    def list_categories(self, merchant_id: uuid.UUID) -> list[CategoryView]:
        return [to_category_view(c) for c in self._products.list_categories(merchant_id)]

    def category_slugs(self, merchant_id: uuid.UUID) -> tuple[str, ...]:
        """The valid category vocabulary, for the search tool's JSON schema.

        ADR-009 (open question B2): enumerating the real slugs means the model
        can only select a category that exists, and an unknown value fails schema
        validation before it reaches a service.
        """
        return tuple(c.slug for c in self._products.list_categories(merchant_id))

    def category_exists(self, merchant_id: uuid.UUID, slug: str) -> bool:
        return self._products.get_category_by_slug(merchant_id, slug) is not None

    # -- relationships -------------------------------------------------------

    def get_related_products(
        self,
        merchant_id: uuid.UUID,
        product_id: uuid.UUID,
        *,
        relationship_types: Sequence[str] | None = None,
    ) -> list[RelatedProduct]:
        """Cross-sell, bundle and related candidates, best priority first.

        Candidates only. R§15 requires a cross-sell to be grounded in
        compatibility, catalog data, bundle rules and user intent, so the caller
        still has to check compatibility and stock before offering any of these.
        Returning them unfiltered is deliberate: this service does not own those
        constraints.
        """
        rows = self._products.related_products(
            merchant_id, product_id, relationship_types=relationship_types
        )
        return [
            RelatedProduct(
                product=to_product_summary(product),
                relationship_type=rel.relationship_type,
                priority=rel.priority,
            )
            for rel, product in rows
        ]
