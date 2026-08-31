"""Builders for the ranking tests.

Not one of these needs a database, and that is the point ADR-004 asks for: *"a
ranker that is unit-testable without a database and without a model; scores
that can be recomputed by hand"*. The ranking engine takes frozen domain values
and returns frozen domain values, so a test can construct the exact catalog it
wants to reason about — including catalogs the seed does not contain, like a
variant with no inventory row or a product belonging to another merchant.

The two products named in the specification's worked example (R§10) are built
here because more than one module asserts against them.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping, Sequence
from decimal import Decimal
from typing import Any

import pytest

from app.domain import ResolvedTarget, StockStatus, StockView, VariantView

MERCHANT_ID = uuid.UUID("00000000-0000-5000-8000-000000000001")
OTHER_MERCHANT_ID = uuid.UUID("00000000-0000-5000-8000-0000000000ff")


def _stable_id(namespace: str, value: str) -> uuid.UUID:
    """A deterministic id, so a failing test names the same row every run."""
    return uuid.uuid5(uuid.NAMESPACE_URL, f"test:{namespace}:{value}")


def make_variant(
    sku: str,
    price: str,
    *,
    product_slug: str | None = None,
    product_name: str | None = None,
    name: str = "Default",
    category_slug: str = "phone_case",
    currency: str = "INR",
    merchant_id: uuid.UUID = MERCHANT_ID,
    brand: str | None = "CircuitCraft",
    product_description: str | None = None,
    attributes: Mapping[str, Any] | None = None,
    product_attributes: Mapping[str, Any] | None = None,
    tags: Sequence[str] = (),
    is_active: bool = True,
    product_is_active: bool = True,
) -> VariantView:
    """A `VariantView` exactly as `CatalogService` would have returned it."""
    slug = product_slug or sku.lower().replace("-", "_")
    return VariantView(
        id=_stable_id("variant", sku),
        sku=sku,
        name=name,
        price=Decimal(price),
        currency=currency,
        merchant_id=merchant_id,
        product_id=_stable_id("product", slug),
        product_slug=slug,
        product_name=product_name or slug.replace("_", " ").title(),
        category_slug=category_slug,
        brand=brand,
        product_description=product_description,
        is_active=is_active,
        product_is_active=product_is_active,
        attributes=dict(attributes or {}),
        product_attributes=dict(product_attributes or {}),
        tags=tuple(tags),
    )


def stock_for(
    variants: Sequence[VariantView], *, quantity: int = 20, missing: Sequence[str] = ()
) -> dict[uuid.UUID, StockView]:
    """A stock map with `quantity` of everything, minus the named SKUs.

    A SKU listed in `missing` gets no entry at all, which is how the schema
    represents a variant with no inventory row — distinct from a recorded zero,
    and both unpurchasable.
    """
    return {
        variant.id: StockView(
            variant_id=variant.id,
            quantity=quantity,
            reserved_quantity=0,
            status=StockStatus.IN_STOCK if quantity > 5 else StockStatus.LOW_STOCK,
        )
        for variant in variants
        if variant.sku not in missing
    }


def out_of_stock(variant: VariantView) -> StockView:
    return StockView(
        variant_id=variant.id,
        quantity=0,
        reserved_quantity=0,
        status=StockStatus.OUT_OF_STOCK,
    )


@pytest.fixture
def merchant_id() -> uuid.UUID:
    return MERCHANT_ID


@pytest.fixture
def iphone_16() -> ResolvedTarget:
    return ResolvedTarget(
        canonical_identifier="iphone_16",
        target_type="phone_model",
        display_name="iPhone 16",
        requested_text="iPhone 16",
        normalized_text="iphone_16",
    )


@pytest.fixture
def aerocase() -> VariantView:
    """PRODUCT A of the R§10 worked example: AeroCase Pro, ₹999."""
    return make_variant(
        "CASE-IP16-BLK",
        "999.00",
        product_slug="aerocase_pro",
        product_name="AeroCase Pro",
        name="Black",
        product_description="Slim protective case for compatible smartphones.",
        attributes={"color": "black"},
        product_attributes={"material": "TPU", "profile": "slim"},
        tags=("iphone", "protective", "slim"),
    )


@pytest.fixture
def shieldcase() -> VariantView:
    """PRODUCT B of the R§10 worked example: ShieldCase Premium, ₹1,299."""
    return make_variant(
        "CASE-IP16-SHD-BLK",
        "1299.00",
        product_slug="shieldcase_premium",
        product_name="ShieldCase Premium",
        name="Black",
        product_description="Rugged protective case with reinforced corners.",
        attributes={"color": "black"},
        product_attributes={"material": "polycarbonate", "profile": "rugged"},
        tags=("iphone", "protective", "premium", "rugged"),
    )


@pytest.fixture
def iphone_15_case() -> VariantView:
    """The trap D§15 describes: cheaper, and for the wrong phone."""
    return make_variant(
        "CASE-IP15-BLK",
        "899.00",
        product_slug="aerocase_pro_15",
        product_name="AeroCase Pro 15",
        name="Black",
        attributes={"color": "black"},
        product_attributes={"material": "TPU", "profile": "slim"},
        tags=("iphone", "protective", "slim"),
    )
