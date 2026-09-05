"""Products, categories and product relationships."""

from __future__ import annotations

import uuid
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

        keys: dict[str, set[str]] = {}
        for slug, product_attributes, variant_attributes in rows:
            bucket = keys.setdefault(slug, set())
            bucket.update(product_attributes or {})
            bucket.update(variant_attributes or {})
        # Sorted, so the payload sent to the model is byte-stable between runs.
        return {slug: tuple(sorted(names)) for slug, names in sorted(keys.items())}

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
