"""Products, categories and product relationships."""

from __future__ import annotations

import uuid
from collections import Counter
from collections.abc import Sequence

from sqlalchemy import Select, select
from sqlalchemy.orm import Session, joinedload

from app.db.models import Category, Product, ProductRelationship, ProductVariant


class ProductRepository:
    """Reads from `products`, `categories` and `product_relationships`."""

    def __init__(self, session: Session) -> None:
        self._session = session

    # -- products ------------------------------------------------------------

    def _base(self, merchant_id: uuid.UUID, *, include_inactive: bool) -> Select[tuple[Product]]:
        statement = (
            select(Product)
            .options(joinedload(Product.category))
            .where(Product.merchant_id == merchant_id)
        )
        if not include_inactive:
            statement = statement.where(Product.is_active.is_(True))
        return statement

    def get(
        self, merchant_id: uuid.UUID, product_id: uuid.UUID, *, include_inactive: bool = False
    ) -> Product | None:
        return self._session.execute(
            self._base(merchant_id, include_inactive=include_inactive).where(
                Product.id == product_id
            )
        ).scalar_one_or_none()

    def get_by_slug(
        self, merchant_id: uuid.UUID, slug: str, *, include_inactive: bool = False
    ) -> Product | None:
        return self._session.execute(
            self._base(merchant_id, include_inactive=include_inactive).where(Product.slug == slug)
        ).scalar_one_or_none()

    def get_many(
        self,
        merchant_id: uuid.UUID,
        product_ids: Sequence[uuid.UUID],
        *,
        include_inactive: bool = False,
    ) -> list[Product]:
        if not product_ids:
            return []
        return list(
            self._session.execute(
                self._base(merchant_id, include_inactive=include_inactive)
                .where(Product.id.in_(product_ids))
                .order_by(Product.slug)
            )
            .scalars()
            .all()
        )

    # -- categories ----------------------------------------------------------

    def list_categories(self, merchant_id: uuid.UUID) -> list[Category]:
        """Every category, ordered by slug so the result is reproducible.

        This is the source of the enumerated `category` vocabulary the agent's
        search tool is constrained to (ADR-009, open question B2).
        """
        return list(
            self._session.execute(
                select(Category)
                .options(joinedload(Category.parent))
                .where(Category.merchant_id == merchant_id)
                .order_by(Category.slug)
            )
            .scalars()
            .all()
        )

    def attribute_keys_by_category(self, merchant_id: uuid.UUID) -> dict[str, tuple[str, ...]]:
        """The attribute names this merchant actually uses, per category slug.

        The same argument as `list_categories` (ADR-009, open question B2), one
        level down. The model is told which categories exist so it cannot name
        one that does not; without this it is told nothing at all about the
        `attributes` field, and a requirement it wants to state as a filter has
        to be guessed at - "noise_cancelling" when the catalogue records `anc`.
        A guessed key does not fail loudly: a missing attribute always fails
        (`app.attributes`), so the search silently returns nothing.

        Read from the rows rather than from a hand-kept list, because the
        merchant dashboard can add an attribute at any time and a list would go
        stale in exactly the direction that hides products.

        Keys are unioned across the product and its variants, because that is
        the view the ranking engine eliminates on (`VariantView.merged_attributes`).
        """
        rows = self._session.execute(
            select(Category.slug, Product.attributes, ProductVariant.attributes)
            .select_from(Category)
            .join(Product, Product.category_id == Category.id)
            .join(ProductVariant, ProductVariant.product_id == Product.id)
            .where(
                Category.merchant_id == merchant_id,
                Product.merchant_id == merchant_id,
                Product.is_active.is_(True),
                ProductVariant.is_active.is_(True),
            )
        ).all()

        counts: dict[str, Counter[str]] = {}
        on_variants: dict[str, set[str]] = {}
        values: dict[str, dict[str, set[str]]] = {}
        for slug, product_attributes, variant_attributes in rows:
            bucket = counts.setdefault(slug, Counter())
            variant_keys = set(variant_attributes or {})
            bucket.update(set(product_attributes or {}) | variant_keys)
            on_variants.setdefault(slug, set()).update(variant_keys)
            seen = values.setdefault(slug, {})
            for name, value in {**(product_attributes or {}), **(variant_attributes or {})}.items():
                seen.setdefault(name, set()).add(repr(value))

        # **Variant-level names first**, then by how many distinct values the
        # name takes in the category, then by how many rows carry it, then
        # alphabetically. Not cosmetic, and not arbitrary: the caller has a
        # hard request-size ceiling and truncates this list, so the order decides
        # what a buyer can still filter on. D§27 makes variant attributes the
        # ones that differentiate sellable versions - storage, memory, capacity,
        # colour - which is exactly what a buyer states as a requirement. Under
        # plain frequency they lost ties alphabetically and `storage_gb` fell off
        # the end of the phone list, so "a phone with 256GB" had no name to use.
        #
        # Distinct values come next, in two steps. A name every product answers
        # the same way is last, because it can never narrow anything: every
        # phone records `operating_system` and they all say the same thing.
        # Among the names that *do* vary, **fewer** distinct values ranks
        # higher - a buyer filters on `network_5g` or `anc`, which are yes or
        # no, far more often than on `battery_mah`, which is a different number
        # on every row and is read rather than searched.
        def order(slug: str) -> list[str]:
            variants = on_variants.get(slug, set())
            distinct = values.get(slug, {})
            return [
                name
                for name, _ in sorted(
                    counts[slug].items(),
                    key=lambda kv: (
                        kv[0] not in variants,
                        len(distinct.get(kv[0], ())) <= 1,
                        len(distinct.get(kv[0], ())),
                        -kv[1],
                        kv[0],
                    ),
                )
            ]

        return {slug: tuple(order(slug)) for slug in sorted(counts)}

    def get_category_by_slug(self, merchant_id: uuid.UUID, slug: str) -> Category | None:
        return self._session.execute(
            select(Category)
            .options(joinedload(Category.parent))
            .where(Category.merchant_id == merchant_id, Category.slug == slug)
        ).scalar_one_or_none()

    # -- relationships -------------------------------------------------------

    def related_products(
        self,
        merchant_id: uuid.UUID,
        product_id: uuid.UUID,
        *,
        relationship_types: Sequence[str] | None = None,
    ) -> list[tuple[ProductRelationship, Product]]:
        """Relationship rows with their target product, cheapest priority first.

        Joined to `products` on the target and scoped to the merchant on that
        join, so a relationship pointing outside the merchant — which the schema
        does not itself forbid, since `product_relationships` carries no
        `merchant_id` — cannot leak another catalog's product into a
        recommendation.
        """
        statement = (
            select(ProductRelationship, Product)
            .join(Product, Product.id == ProductRelationship.target_product_id)
            .options(joinedload(Product.category))
            .where(
                ProductRelationship.source_product_id == product_id,
                Product.merchant_id == merchant_id,
                Product.is_active.is_(True),
            )
            .order_by(ProductRelationship.priority, Product.slug)
        )
        if relationship_types:
            statement = statement.where(
                ProductRelationship.relationship_type.in_(relationship_types)
            )
        return [(rel, product) for rel, product in self._session.execute(statement).all()]
