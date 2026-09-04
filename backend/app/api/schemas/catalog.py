"""Response models for the read-only catalog routes.

These exist so a buyer can *browse*. Until now the only way a product reached
the UI was as `recommendations[]` on a chat turn, which made a storefront
impossible to build without inventing data — exactly what F§9 forbids.

Nothing here computes, adjusts or infers a commerce fact. Every field is copied
from a `VariantView`, a `ProductSummary` or a `StockView`, all of which come
from PostgreSQL through the deterministic services (ADR-001, ADR-002). No model
is involved in any of it: these routes never touch `app.llm` or `app.agent`.

`CatalogItem` deliberately mirrors the chat turn's `Recommendation` field for
field, minus the ranking-only members (`rank`, `reason`, `reason_code`,
`score`). One shape means the frontend renders a browsed product and an
agent-recommended product with the same component, which is what lets the
assistant feel like part of the storefront rather than a panel bolted beside it.
"""

from __future__ import annotations

import uuid
from typing import Any

from pydantic import BaseModel, Field

from app.domain.catalog import CategoryView, ProductSummary, VariantView
from app.domain.inventory import StockView

__all__ = [
    "CatalogItem",
    "CategoryItem",
    "ProductDetailResponse",
    "ProductListResponse",
]


class CategoryItem(BaseModel):
    """One merchant category."""

    id: uuid.UUID
    slug: str
    name: str
    parent_slug: str | None = None

    @classmethod
    def of(cls, view: CategoryView) -> CategoryItem:
        return cls(id=view.id, slug=view.slug, name=view.name, parent_slug=view.parent_slug)


class CatalogItem(BaseModel):
    """One sellable variant, shaped like a chat `Recommendation`.

    `price` is a **string** for the same reason it is everywhere else in this
    API: `json.loads` turns `999.00` into a float before validation can
    intervene, and a float is not a price (ADR-008).
    """

    product_id: uuid.UUID
    variant_id: uuid.UUID
    product_slug: str
    sku: str
    name: str
    variant_name: str
    category: str
    price: str = Field(description="Fixed-scale decimal string, never a JSON number.")
    currency: str
    stock_status: str
    attributes: dict[str, Any] = Field(default_factory=dict)
    tags: list[str] = Field(default_factory=list)
    brand: str | None = None
    description: str | None = None

    @classmethod
    def of(cls, variant: VariantView, stock: StockView | None) -> CatalogItem:
        return cls(
            product_id=variant.product_id,
            variant_id=variant.id,
            product_slug=variant.product_slug,
            sku=variant.sku,
            name=variant.product_name,
            variant_name=variant.name,
            category=variant.category_slug,
            # `str(Decimal)` preserves the stored scale; formatting it would be a
            # second place that decides what a price looks like.
            price=str(variant.price),
            currency=variant.currency,
            # A variant with no inventory row is not "probably fine" — the
            # `StockView.missing` path already answers OUT_OF_STOCK, and `None`
            # here means the caller did not ask for stock at all.
            stock_status=(stock.status.value if stock is not None else "OUT_OF_STOCK"),
            attributes=variant.merged_attributes,
            tags=list(variant.tags),
            brand=variant.brand,
            description=variant.product_description,
        )


class ProductListResponse(BaseModel):
    """A page of variants, plus the facets a listing UI needs to render itself."""

    items: list[CatalogItem]
    total: int = Field(description="Rows matched before `limit` was applied.")
    categories: list[CategoryItem] = Field(default_factory=list)


class ProductSummaryItem(BaseModel):
    """Product identity without its variants — for related-product strips."""

    id: uuid.UUID
    slug: str
    name: str
    category: str
    brand: str | None = None
    description: str | None = None

    @classmethod
    def of(cls, summary: ProductSummary) -> ProductSummaryItem:
        return cls(
            id=summary.id,
            slug=summary.slug,
            name=summary.name,
            category=summary.category_slug,
            brand=summary.brand,
            description=summary.description,
        )


class ProductDetailResponse(BaseModel):
    """One product and every sellable version of it."""

    product: ProductSummaryItem
    variants: list[CatalogItem]
    related: list[ProductSummaryItem] = Field(default_factory=list)
