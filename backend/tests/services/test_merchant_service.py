"""`MerchantCatalogService` / `MerchantAnalyticsService` — the dashboard's write side.

Against a real database (ADR-002): the whole point is that a merchant edit
becomes a row PostgreSQL holds, checked by the same CHECK constraints the seed
obeys. The properties under test:

* a created product/variant is real, scoped to the merchant, and validated;
* money stays a string with two places, never a float;
* stock changes go *through* the schema, never around it;
* **merchant isolation** — a service scoped to one merchant cannot read or write
  another merchant's catalogue, even given a real id for the other one.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from sqlalchemy.orm import Session

from app.db.models import Category, Inventory, Merchant, Product, ProductVariant
from app.services.catalog_service import CatalogService
from app.services.merchant_service import (
    MerchantAnalyticsService,
    MerchantCatalogService,
    MerchantError,
)

pytestmark = pytest.mark.requires_db


@pytest.fixture
def other_merchant(session: Session) -> uuid.UUID:
    """A second merchant with one product, for isolation tests. Rolled back."""
    mid = uuid.uuid4()
    session.add(Merchant(id=mid, name=f"Rival {mid.hex[:8]}", currency="INR", is_active=True))
    session.flush()
    cat = Category(id=uuid.uuid4(), merchant_id=mid, name="Widgets", slug="widgets")
    session.add(cat)
    session.flush()
    prod = Product(
        id=uuid.uuid4(),
        merchant_id=mid,
        category_id=cat.id,
        name="Rival Widget",
        slug="rival_widget",
        attributes={},
        tags=[],
        is_active=True,
    )
    session.add(prod)
    session.flush()
    var = ProductVariant(
        id=uuid.uuid4(),
        merchant_id=mid,
        product_id=prod.id,
        sku="RIVAL-1",
        name="Default",
        price=Decimal("500.00"),
        currency="INR",
        attributes={},
        is_active=True,
    )
    session.add(var)
    session.flush()
    session.add(Inventory(id=uuid.uuid4(), variant_id=var.id, quantity=10, reserved_quantity=0))
    session.flush()
    return mid


# -- create ---------------------------------------------------------------


def test_create_product_with_variants_is_real_and_scoped(session: Session, merchant_id) -> None:
    svc = MerchantCatalogService(session)
    detail = svc.create_product(
        merchant_id,
        name="Test Merino Beanie",
        category_slug="t_shirt",
        description="A warm hat.",
        attributes={"material": "merino_wool"},
        tags=["hat", "winter"],
        variants=[
            {"sku": "TEST-BEANIE-BLK", "name": "Black", "price": "899.00", "quantity": 7},
            {"sku": "TEST-BEANIE-GRY", "name": "Grey", "price": "899.00", "quantity": 0},
        ],
    )
    assert detail.product.slug == "test_merino_beanie"
    assert len(detail.variants) == 2
    # It is visible through the read service, at the price given, scoped to us.
    listed = CatalogService(session).get_product_by_slug(merchant_id, "test_merino_beanie")
    assert listed is not None
    prices = {v.sku: v.price for v in listed.variants}
    assert prices == {"TEST-BEANIE-BLK": Decimal("899.00"), "TEST-BEANIE-GRY": Decimal("899.00")}
    for v in listed.variants:
        assert v.merchant_id == merchant_id


def test_create_product_rejects_a_json_number_price(session: Session, merchant_id) -> None:
    svc = MerchantCatalogService(session)
    with pytest.raises(MerchantError) as exc:
        svc.create_product(
            merchant_id,
            name="Bad",
            category_slug="t_shirt",
            variants=[{"sku": "BAD-1", "name": "X", "price": 899.0, "quantity": 1}],
        )
    assert exc.value.code == "VALIDATION_ERROR"
    assert "not a number" in exc.value.message or "decimal string" in exc.value.message


def test_create_product_rejects_a_duplicate_sku(session: Session, merchant_id) -> None:
    svc = MerchantCatalogService(session)
    with pytest.raises(MerchantError):
        svc.create_product(
            merchant_id,
            name="Dupe",
            category_slug="charger",
            variants=[{"sku": "CHARGER-30W", "name": "X", "price": "1.00", "quantity": 1}],
        )


def test_create_product_rejects_an_unknown_category(session: Session, merchant_id) -> None:
    svc = MerchantCatalogService(session)
    with pytest.raises(MerchantError) as exc:
        svc.create_product(merchant_id, name="X", category_slug="not_a_category")
    assert exc.value.code == "VALIDATION_ERROR"


def test_more_than_two_decimal_places_is_rejected(session: Session, merchant_id) -> None:
    svc = MerchantCatalogService(session)
    with pytest.raises(MerchantError):
        svc.create_product(
            merchant_id,
            name="X",
            category_slug="t_shirt",
            variants=[{"sku": "X-1", "name": "X", "price": "10.001", "quantity": 1}],
        )


# -- update -------------------------------------------------------------


def test_update_variant_price_is_a_string_and_takes_effect(
    session: Session, merchant_id, variant_id
) -> None:
    svc = MerchantCatalogService(session)
    vid = variant_id("CHARGER-30W")
    svc.update_variant(merchant_id, vid, price="1599.00")
    got = CatalogService(session).get_authoritative_price(merchant_id, vid)
    assert got == (Decimal("1599.00"), "INR")


def test_archive_hides_the_product_from_the_storefront(
    session: Session, merchant_id, product_id
) -> None:
    svc = MerchantCatalogService(session)
    pid = product_id("everyday_cotton_crew")
    svc.set_product_active(merchant_id, pid, active=False)
    # The read service (storefront) no longer sees it...
    assert CatalogService(session).get_product(merchant_id, pid) is None
    # ...but the dashboard still can, and can restore it.
    assert svc.get_product(merchant_id, pid).product.slug == "everyday_cotton_crew"
    svc.set_product_active(merchant_id, pid, active=True)
    assert CatalogService(session).get_product(merchant_id, pid) is not None


# -- stock --------------------------------------------------------------


def test_set_stock_goes_through_the_schema(session: Session, merchant_id, variant_id) -> None:
    svc = MerchantCatalogService(session)
    vid = variant_id("BUDS-LITE")
    row = svc.set_stock(merchant_id, vid, quantity=3)
    assert row.available_quantity == 3
    assert row.stock_status.value == "LOW_STOCK"
    row = svc.set_stock(merchant_id, vid, quantity=0)
    assert row.stock_status.value == "OUT_OF_STOCK"


def test_set_stock_rejects_a_negative_quantity(session: Session, merchant_id, variant_id) -> None:
    svc = MerchantCatalogService(session)
    with pytest.raises(MerchantError):
        svc.set_stock(merchant_id, variant_id("BUDS-LITE"), quantity=-1)


# -- categories -------------------------------------------------------


def test_create_category_slugifies_and_nests(session: Session, merchant_id) -> None:
    svc = MerchantCatalogService(session)
    cat = svc.create_category(merchant_id, name="Winter Hats", parent_slug="clothing")
    assert cat.slug == "winter_hats"
    slugs = {c.slug for c in CatalogService(session).list_categories(merchant_id)}
    assert "winter_hats" in slugs


# -- MERCHANT ISOLATION ---------------------------------------------


def test_cannot_read_another_merchants_product(
    session: Session, merchant_id, other_merchant
) -> None:
    rival_product = session.query(Product).filter(Product.merchant_id == other_merchant).one()
    svc = MerchantCatalogService(session)
    with pytest.raises(MerchantError) as exc:
        svc.get_product(merchant_id, rival_product.id)  # a real id, wrong merchant
    assert exc.value.code == "PRODUCT_NOT_FOUND"


def test_cannot_edit_another_merchants_variant(
    session: Session, merchant_id, other_merchant
) -> None:
    rival_variant = (
        session.query(ProductVariant).filter(ProductVariant.merchant_id == other_merchant).one()
    )
    svc = MerchantCatalogService(session)
    with pytest.raises(MerchantError) as exc:
        svc.update_variant(merchant_id, rival_variant.id, price="1.00")
    assert exc.value.code == "VARIANT_NOT_FOUND"
    # And the rival's price is untouched.
    session.refresh(rival_variant)
    assert rival_variant.price == Decimal("500.00")


def test_cannot_set_stock_on_another_merchants_variant(
    session: Session, merchant_id, other_merchant
) -> None:
    rival_variant = (
        session.query(ProductVariant).filter(ProductVariant.merchant_id == other_merchant).one()
    )
    svc = MerchantCatalogService(session)
    with pytest.raises(MerchantError):
        svc.set_stock(merchant_id, rival_variant.id, quantity=999)


def test_list_products_never_shows_another_merchants_rows(
    session: Session, merchant_id, other_merchant
) -> None:
    svc = MerchantCatalogService(session)
    page = svc.list_products(merchant_id, limit=100, offset=0)
    skus = {r.sku for r in page.rows}
    assert "RIVAL-1" not in skus
    page2 = svc.list_products(merchant_id, search="RIVAL", limit=100, offset=0)
    assert page2.rows == ()


# -- analytics --------------------------------------------------------


def test_overview_counts_are_real(session: Session, merchant_id, other_merchant) -> None:
    ov = MerchantAnalyticsService(session).overview(merchant_id)
    # The seed: 51 products, 216 variants. The rival's product is not counted.
    assert ov.total_products == 51
    assert ov.total_variants == 216
    assert ov.category_count == 24
    assert ov.total_inventory_units > 0
    assert ov.out_of_stock_variants >= 9  # the seed's deliberate OOS variants
    # No orders were placed in this rolled-back test, so revenue is exactly zero.
    assert ov.revenue == Decimal("0.00")
    assert ov.paid_orders == 0
