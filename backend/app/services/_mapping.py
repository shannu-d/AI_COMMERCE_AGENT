"""ORM rows to domain types.

One place, so every service produces identically-shaped results and no caller
ever receives a live ORM instance (see `app.domain`).
"""

from __future__ import annotations

from app.db.models import Category, CompatibilityTarget, Inventory, Product, ProductVariant
from app.domain import (
    CategoryView,
    CompatibilityTargetView,
    ProductSummary,
    StockStatus,
    StockView,
    VariantView,
)


def to_category_view(category: Category) -> CategoryView:
    return CategoryView(
        id=category.id,
        slug=category.slug,
        name=category.name,
        parent_slug=category.parent.slug if category.parent else None,
    )


def to_product_summary(product: Product) -> ProductSummary:
    return ProductSummary(
        id=product.id,
        slug=product.slug,
        name=product.name,
        category_slug=product.category.slug,
        brand=product.brand,
        description=product.description,
        attributes=dict(product.attributes),
        tags=tuple(product.tags),
    )


def to_variant_view(variant: ProductVariant) -> VariantView:
    product = variant.product
    return VariantView(
        id=variant.id,
        sku=variant.sku,
        name=variant.name,
        price=variant.price,
        currency=variant.currency,
        merchant_id=variant.merchant_id,
        product_id=product.id,
        product_slug=product.slug,
        product_name=product.name,
        category_slug=product.category.slug,
        brand=product.brand,
        product_description=product.description,
        is_active=variant.is_active,
        product_is_active=product.is_active,
        attributes=dict(variant.attributes),
        product_attributes=dict(product.attributes),
        tags=tuple(product.tags),
    )


def to_compatibility_target_view(target: CompatibilityTarget) -> CompatibilityTargetView:
    return CompatibilityTargetView(
        id=target.id,
        target_type=target.target_type,
        canonical_identifier=target.canonical_identifier,
        display_name=target.display_name,
        aliases=tuple(target.aliases),
    )


def to_stock_view(inventory: Inventory, *, low_stock_threshold: int) -> StockView:
    available = inventory.quantity - inventory.reserved_quantity
    if available <= 0:
        status = StockStatus.OUT_OF_STOCK
    elif available <= low_stock_threshold:
        status = StockStatus.LOW_STOCK
    else:
        status = StockStatus.IN_STOCK
    return StockView(
        variant_id=inventory.variant_id,
        quantity=inventory.quantity,
        reserved_quantity=inventory.reserved_quantity,
        status=status,
    )
