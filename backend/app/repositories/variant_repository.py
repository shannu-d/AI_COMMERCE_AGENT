"""Product variants — the sellable unit, and therefore the search unit."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session, joinedload

from app.db.models import Category, Product, ProductVariant


@dataclass(frozen=True, slots=True)
class VariantQuery:
    """Catalog filters that belong to the catalog itself.

    Compatibility and inventory are deliberately **absent**. They are separate
    hard constraints owned by their own services (ADR-005), and M3's filter
    composes all three. Folding them in here would make the catalog query the
    place where the eliminating rules live, which is exactly the coupling the
    architecture separates.
    """

    category_slug: str | None = None
    #: Free text matched against product name and description, case-insensitively.
    search_text: str | None = None
    max_price: Decimal | None = None
    currency: str | None = None
    #: Matched against the variant's own attributes, then the product's, as a
    #: JSONB containment test.
    attributes: dict[str, Any] = field(default_factory=dict)
    include_inactive: bool = False
    limit: int | None = None
    #: Row offset, for the merchant dashboard's paginated product list. The
    #: storefront never sets this — it pages in the route over a small result.
    offset: int = 0


class VariantRepository:
    """Reads from `product_variants`, joined to its product and category."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def _base(
        self, merchant_id: uuid.UUID, *, include_inactive: bool
    ) -> Select[tuple[ProductVariant]]:
        statement = (
            select(ProductVariant)
            .join(Product, Product.id == ProductVariant.product_id)
            .options(joinedload(ProductVariant.product).joinedload(Product.category))
            .where(ProductVariant.merchant_id == merchant_id)
        )
        if not include_inactive:
            # Both must be active: an active variant of a deactivated product is
            # not sellable.
            statement = statement.where(
                ProductVariant.is_active.is_(True), Product.is_active.is_(True)
            )
        return statement

    def get(
        self, merchant_id: uuid.UUID, variant_id: uuid.UUID, *, include_inactive: bool = False
    ) -> ProductVariant | None:
        return self._session.execute(
            self._base(merchant_id, include_inactive=include_inactive).where(
                ProductVariant.id == variant_id
            )
        ).scalar_one_or_none()

    def get_by_sku(
        self, merchant_id: uuid.UUID, sku: str, *, include_inactive: bool = False
    ) -> ProductVariant | None:
        """SKU lookup, scoped to the merchant.

        `UNIQUE(merchant_id, sku)` (D§10, D§23) is what makes this single-valued;
        SKU is not globally unique, so a lookup without a merchant would be
        ambiguous by construction.
        """
        return self._session.execute(
            self._base(merchant_id, include_inactive=include_inactive).where(
                ProductVariant.sku == sku
            )
        ).scalar_one_or_none()

    def get_many(
        self,
        merchant_id: uuid.UUID,
        variant_ids: Sequence[uuid.UUID],
        *,
        include_inactive: bool = False,
    ) -> list[ProductVariant]:
        if not variant_ids:
            return []
        return list(
            self._session.execute(
                self._base(merchant_id, include_inactive=include_inactive)
                .where(ProductVariant.id.in_(variant_ids))
                .order_by(ProductVariant.sku)
            )
            .scalars()
            .all()
        )

    def for_products(
        self,
        merchant_id: uuid.UUID,
        product_ids: Sequence[uuid.UUID],
        *,
        include_inactive: bool = False,
    ) -> list[ProductVariant]:
        if not product_ids:
            return []
        return list(
            self._session.execute(
                self._base(merchant_id, include_inactive=include_inactive)
                .where(ProductVariant.product_id.in_(product_ids))
                .order_by(ProductVariant.sku)
            )
            .scalars()
            .all()
        )

    def _filtered(
        self, merchant_id: uuid.UUID, query: VariantQuery
    ) -> Select[tuple[ProductVariant]]:
        """The `search` filters, without ordering, limit or offset.

        Split out so `search` and `count` cannot drift about what a query
        matches.
        """
        statement = self._base(merchant_id, include_inactive=query.include_inactive)

        if query.category_slug is not None:
            statement = statement.join(Category, Category.id == Product.category_id).where(
                Category.slug == query.category_slug
            )

        if query.max_price is not None:
            statement = statement.where(ProductVariant.price <= query.max_price)

        if query.currency is not None:
            statement = statement.where(ProductVariant.currency == query.currency)

        if query.search_text:
            # ILIKE rather than a text index: a deterministic substring match is
            # explainable in a way a relevance-ranked full-text query is not. M3
            # scores text relevance separately (ADR-004). Also matches SKU, which
            # the merchant dashboard's search box needs.
            pattern = f"%{query.search_text.strip()}%"
            statement = statement.where(
                Product.name.ilike(pattern)
                | Product.description.ilike(pattern)
                | ProductVariant.name.ilike(pattern)
                | ProductVariant.sku.ilike(pattern)
            )

        for key, value in query.attributes.items():
            # JSONB containment against the variant first, then the product, so
            # a variant-level attribute overrides its product's (D§27).
            statement = statement.where(
                ProductVariant.attributes.contains({key: value})
                | Product.attributes.contains({key: value})
            )

        return statement

    def search(self, merchant_id: uuid.UUID, query: VariantQuery) -> list[ProductVariant]:
        """Catalog search. One row per variant (ADR-009, open question B7).

        Ordering is `(price, sku)`: deterministic and stable, so the same query
        against the same catalog always returns the same sequence. Ranking is
        M3's job and does not happen here — R§8 requires ranking to be
        deterministic, and a search that quietly imposed its own order would
        make the ranker's output depend on it.
        """
        statement = self._filtered(merchant_id, query).order_by(
            ProductVariant.price, ProductVariant.sku
        )
        if query.offset:
            statement = statement.offset(query.offset)
        if query.limit is not None:
            statement = statement.limit(query.limit)
        return list(self._session.execute(statement).scalars().all())

    def count(self, merchant_id: uuid.UUID, query: VariantQuery) -> int:
        """How many variants match `query`, ignoring limit/offset.

        For the merchant dashboard's paginated list, so a page can say "showing
        1-25 of 216".
        """
        subquery = self._filtered(merchant_id, query).order_by(None).subquery()
        return int(self._session.execute(select(func.count()).select_from(subquery)).scalar_one())
