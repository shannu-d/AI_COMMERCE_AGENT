"""Request and response models for the merchant dashboard API.

**Requests forbid unknown fields** (`extra="forbid"`), the same rule the chat and
cart APIs follow: a field the schema does not define is a client bug or a
protocol drift, and dropping it silently is how a typo becomes a no-op the
merchant does not notice.

**Money is a string in and out** (ADR-008). A JSON number for a price is
rejected — it would already have been through `float` before any validator saw
it.

The heavy validation (SKU shape, slug canonicalisation, price scale, category
ownership, merchant scoping) lives in `MerchantCatalogService`, so it holds
whether a write arrives through this API or any future one. These models only
pin the request *shape*.
"""

from __future__ import annotations

import uuid
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.services.merchant_service import (
    MerchantOverview,
    MerchantProductPage,
    MerchantProductRow,
)

__all__ = [
    "CategoryCreateRequest",
    "MerchantCategoryItem",
    "MerchantOrderItem",
    "MerchantOrderLine",
    "MerchantOrderPage",
    "MerchantOverviewResponse",
    "MerchantProductDetailResponse",
    "MerchantProductListResponse",
    "MerchantVariantItem",
    "ProductCreateRequest",
    "ProductUpdateRequest",
    "StockUpdateRequest",
    "VariantCreateRequest",
    "VariantInput",
    "VariantUpdateRequest",
]


class _Request(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


# -- write requests -------------------------------------------------------


class VariantInput(_Request):
    sku: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=255)
    price: str = Field(description='Decimal string, e.g. "1499.00". Never a JSON number.')
    quantity: int = Field(default=0, ge=0, le=1_000_000)
    attributes: dict[str, Any] = Field(default_factory=dict)


class ProductCreateRequest(_Request):
    name: str = Field(min_length=1, max_length=255)
    category: str = Field(min_length=1, description="An existing category slug.")
    description: str | None = Field(default=None, max_length=4000)
    brand: str | None = Field(default=None, max_length=128)
    slug: str | None = Field(default=None, max_length=160)
    attributes: dict[str, Any] = Field(default_factory=dict)
    tags: list[str] = Field(default_factory=list)
    variants: list[VariantInput] = Field(default_factory=list, max_length=60)


class ProductUpdateRequest(_Request):
    # `None` is a meaningful value for description/brand (clear the field), so the
    # route inspects `model_fields_set` to tell "not sent" from "sent as null".
    name: str | None = Field(default=None, min_length=1, max_length=255)
    category: str | None = Field(default=None, min_length=1)
    description: str | None = Field(default=None, max_length=4000)
    brand: str | None = Field(default=None, max_length=128)
    attributes: dict[str, Any] | None = None
    tags: list[str] | None = None
    is_active: bool | None = None


class VariantCreateRequest(VariantInput):
    pass


class VariantUpdateRequest(_Request):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    price: str | None = None
    attributes: dict[str, Any] | None = None
    is_active: bool | None = None


class StockUpdateRequest(_Request):
    quantity: int = Field(ge=0, le=1_000_000)


class CategoryCreateRequest(_Request):
    name: str = Field(min_length=1, max_length=255)
    slug: str | None = Field(default=None, max_length=128)
    parent: str | None = Field(default=None, description="An existing category slug.")


# -- responses ----------------------------------------------------------


class MerchantVariantItem(BaseModel):
    variant_id: uuid.UUID
    product_id: uuid.UUID
    product_slug: str
    product_name: str
    variant_name: str
    sku: str
    category: str
    price: str
    currency: str
    quantity: int
    reserved_quantity: int
    available_quantity: int
    stock_status: str
    product_active: bool
    variant_active: bool
    attributes: dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def of(cls, row: MerchantProductRow) -> MerchantVariantItem:
        return cls(
            variant_id=row.variant_id,
            product_id=row.product_id,
            product_slug=row.product_slug,
            product_name=row.product_name,
            variant_name=row.variant_name,
            sku=row.sku,
            category=row.category,
            price=str(row.price),
            currency=row.currency,
            quantity=row.quantity,
            reserved_quantity=row.reserved_quantity,
            available_quantity=row.available_quantity,
            stock_status=row.stock_status.value,
            product_active=row.product_active,
            variant_active=row.variant_active,
            attributes=dict(row.attributes),
        )


class MerchantProductListResponse(BaseModel):
    items: list[MerchantVariantItem]
    total: int
    limit: int
    offset: int

    @classmethod
    def of(cls, page: MerchantProductPage) -> MerchantProductListResponse:
        return cls(
            items=[MerchantVariantItem.of(r) for r in page.rows],
            total=page.total,
            limit=page.limit,
            offset=page.offset,
        )


class MerchantProductDetailResponse(BaseModel):
    product_id: uuid.UUID
    slug: str
    name: str
    category: str
    description: str | None = None
    brand: str | None = None
    is_active: bool
    attributes: dict[str, Any] = Field(default_factory=dict)
    tags: list[str] = Field(default_factory=list)
    variants: list[MerchantVariantItem]


class MerchantCategoryItem(BaseModel):
    id: uuid.UUID
    slug: str
    name: str
    parent_slug: str | None = None


class MerchantOverviewResponse(BaseModel):
    currency: str
    total_products: int
    active_products: int
    archived_products: int
    total_variants: int
    active_variants: int
    total_inventory_units: int
    out_of_stock_variants: int
    low_stock_variants: int
    category_count: int
    total_orders: int
    paid_orders: int
    revenue: str

    @classmethod
    def of(cls, overview: MerchantOverview) -> MerchantOverviewResponse:
        return cls(
            currency=overview.currency,
            total_products=overview.total_products,
            active_products=overview.active_products,
            archived_products=overview.archived_products,
            total_variants=overview.total_variants,
            active_variants=overview.active_variants,
            total_inventory_units=overview.total_inventory_units,
            out_of_stock_variants=overview.out_of_stock_variants,
            low_stock_variants=overview.low_stock_variants,
            category_count=overview.category_count,
            total_orders=overview.total_orders,
            paid_orders=overview.paid_orders,
            revenue=str(overview.revenue),
        )


class MerchantOrderLine(BaseModel):
    sku: str
    product_name: str
    variant_name: str
    quantity: int
    unit_price: str
    line_total: str


class MerchantOrderItem(BaseModel):
    order_id: uuid.UUID
    status: str
    currency: str
    subtotal_amount: str
    total_amount: str
    cart_version: int
    razorpay_order_id: str | None = None
    created_at: str
    items: list[MerchantOrderLine] = Field(default_factory=list)


class MerchantOrderPage(BaseModel):
    items: list[MerchantOrderItem]
    total: int
    limit: int
    offset: int
