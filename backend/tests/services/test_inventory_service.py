"""InventoryService — authoritative availability.

The property under test is the pre-submission gate item PG-1: out-of-stock
products are safely blocked. "Safely" is doing work — the service fails closed
on every form of not-knowing, including a variant with no inventory row at all.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from sqlalchemy.orm import Session

from app.db.models import Inventory, ProductVariant
from app.domain import StockStatus, StockView
from app.services import InventoryService
from tests.services.conftest import OTHER_MERCHANT_ID

pytestmark = pytest.mark.requires_db


# --------------------------------------------------------------------------
# 11. In stock
# --------------------------------------------------------------------------


def test_a_stocked_variant_reports_in_stock(
    inventory: InventoryService, merchant_id: uuid.UUID, variant_id
) -> None:
    stock = inventory.get_stock(merchant_id, variant_id("CASE-IP16-BLK"))

    assert stock.quantity == 20
    assert stock.reserved_quantity == 0
    assert stock.available_quantity == 20
    assert stock.status is StockStatus.IN_STOCK
    assert stock.is_purchasable


def test_availability_compares_against_the_requested_quantity(
    inventory: InventoryService, merchant_id: uuid.UUID, variant_id
) -> None:
    """D§29 step 6: enough for the request, not merely non-zero."""
    vid = variant_id("CASE-IP16-SHD-BLK")  # quantity 5

    assert inventory.check_availability(merchant_id, vid, 5).available
    assert not inventory.check_availability(merchant_id, vid, 6).available

    short = inventory.check_availability(merchant_id, vid, 8)
    assert short.available_quantity == 5
    assert short.shortfall == 3


def test_low_stock_is_reported_separately_from_in_stock(
    inventory: InventoryService, merchant_id: uuid.UUID, variant_id
) -> None:
    """ADR-009's coarse buyer-facing status."""
    assert (
        inventory.stock_status(merchant_id, variant_id("CASE-IP16-SHD-BLK"))
        is StockStatus.LOW_STOCK  # quantity 5, threshold 5
    )
    assert inventory.stock_status(merchant_id, variant_id("CASE-IP16-BLK")) is StockStatus.IN_STOCK


def test_the_low_stock_threshold_is_configurable_not_hard_coded(
    session: Session, merchant_id: uuid.UUID, variant_id
) -> None:
    generous = InventoryService(session, low_stock_threshold=100)

    assert generous.stock_status(merchant_id, variant_id("CASE-IP16-BLK")) is StockStatus.LOW_STOCK


# --------------------------------------------------------------------------
# 12. Out of stock
# --------------------------------------------------------------------------


def test_a_zero_quantity_variant_is_out_of_stock_and_unpurchasable(
    inventory: InventoryService, merchant_id: uuid.UUID, variant_id
) -> None:
    """RULE 5, R§6: Compatible + Out of Stock != Purchasable."""
    stock = inventory.get_stock(merchant_id, variant_id("CASE-IP16-CLR"))

    assert stock.quantity == 0
    assert stock.status is StockStatus.OUT_OF_STOCK
    assert not stock.is_purchasable
    assert not inventory.is_available(merchant_id, variant_id("CASE-IP16-CLR"))


def test_reserved_stock_reduces_what_is_available(
    session: Session, inventory: InventoryService, merchant_id: uuid.UUID, variant_id
) -> None:
    """D§11: available = quantity - reserved.

    Nothing writes `reserved_quantity` in the MVP (ADR-005), but the arithmetic
    must already be right for when something does.
    """
    vid = variant_id("CASE-IP16-BLK")
    row = session.execute(Inventory.__table__.select().where(Inventory.variant_id == vid)).one()
    session.get(Inventory, row.id).reserved_quantity = 20
    session.flush()

    stock = inventory.get_stock(merchant_id, vid)

    assert stock.quantity == 20
    assert stock.available_quantity == 0
    assert stock.status is StockStatus.OUT_OF_STOCK
    assert not inventory.is_available(merchant_id, vid)


def test_filter_available_removes_the_out_of_stock_and_keeps_the_order(
    inventory: InventoryService, merchant_id: uuid.UUID, variant_id
) -> None:
    ordered = [
        variant_id("CASE-IP16-CLR"),  # 0
        variant_id("CASE-IP16-BLK"),  # 20
        variant_id("CASE-IP16-BLU"),  # 12
    ]

    kept = inventory.filter_available(merchant_id, ordered)

    assert kept == [variant_id("CASE-IP16-BLK"), variant_id("CASE-IP16-BLU")]


def test_filter_available_respects_the_requested_quantity(
    inventory: InventoryService, merchant_id: uuid.UUID, variant_id
) -> None:
    ids = [variant_id("CASE-IP16-BLK"), variant_id("CASE-IP16-SHD-BLK")]

    assert inventory.filter_available(merchant_id, ids, quantity=5) == ids
    assert inventory.filter_available(merchant_id, ids, quantity=15) == [
        variant_id("CASE-IP16-BLK")
    ]


# --------------------------------------------------------------------------
# 13. Missing inventory record
# --------------------------------------------------------------------------


def test_a_variant_with_no_inventory_row_is_reported_and_blocked(
    session: Session, inventory: InventoryService, merchant_id: uuid.UUID, product_id
) -> None:
    """The schema permits it: `inventory` points at the variant, not the reverse.

    "We know there are none" and "we have no idea" are both unpurchasable, and
    only one of them is a data problem — so they are distinguishable rather than
    flattened into a zero.
    """
    orphan = ProductVariant(
        merchant_id=merchant_id,
        product_id=product_id("aerocase_pro"),
        sku="NOINV-1",
        name="No inventory row",
        price=Decimal("1.00"),
        currency="INR",
    )
    session.add(orphan)
    session.flush()

    stock = inventory.get_stock(merchant_id, orphan.id)

    assert stock.status is StockStatus.NO_RECORD
    assert stock.status is not StockStatus.OUT_OF_STOCK
    assert stock.available_quantity == 0
    assert not stock.is_purchasable
    assert not inventory.is_available(merchant_id, orphan.id)
    assert inventory.filter_available(merchant_id, [orphan.id]) == []


def test_an_unknown_variant_is_also_no_record_rather_than_an_error(
    inventory: InventoryService, merchant_id: uuid.UUID
) -> None:
    stock = inventory.get_stock(merchant_id, uuid.uuid4())

    assert stock.status is StockStatus.NO_RECORD
    assert not stock.is_purchasable


def test_stock_view_missing_is_never_purchasable() -> None:
    """Pure, no database: the fail-closed default itself."""
    view = StockView.missing(uuid.uuid4())

    assert view.available_quantity == 0
    assert not view.is_purchasable
    assert view.status is StockStatus.NO_RECORD


# --------------------------------------------------------------------------
# Scoping, batching, determinism
# --------------------------------------------------------------------------


def test_inventory_is_merchant_scoped(inventory: InventoryService, variant_id) -> None:
    """`inventory` carries no merchant_id; scoping comes from the variant join."""
    stock = inventory.get_stock(OTHER_MERCHANT_ID, variant_id("CASE-IP16-BLK"))

    assert stock.status is StockStatus.NO_RECORD
    assert stock.quantity == 0


def test_the_batch_lookup_covers_every_requested_id(
    session: Session, inventory: InventoryService, merchant_id: uuid.UUID, variant_id, product_id
) -> None:
    """No caller should have to decide what a missing key means."""
    orphan = ProductVariant(
        merchant_id=merchant_id,
        product_id=product_id("aerocase_pro"),
        sku="NOINV-2",
        name="No inventory row",
        price=Decimal("1.00"),
        currency="INR",
    )
    session.add(orphan)
    session.flush()

    unknown = uuid.uuid4()
    requested = [variant_id("CASE-IP16-BLK"), variant_id("CASE-IP16-CLR"), orphan.id, unknown]

    stock_map = inventory.get_stock_map(merchant_id, requested)

    assert set(stock_map) == set(requested)
    assert stock_map[variant_id("CASE-IP16-BLK")].status is StockStatus.IN_STOCK
    assert stock_map[variant_id("CASE-IP16-CLR")].status is StockStatus.OUT_OF_STOCK
    assert stock_map[orphan.id].status is StockStatus.NO_RECORD
    assert stock_map[unknown].status is StockStatus.NO_RECORD


def test_the_batch_lookup_agrees_with_the_single_lookup(
    inventory: InventoryService, merchant_id: uuid.UUID, variant_id
) -> None:
    ids = [variant_id(sku) for sku in ("CASE-IP16-BLK", "CASE-IP16-CLR", "BUDS-LITE")]
    batch = inventory.get_stock_map(merchant_id, ids)

    for vid in ids:
        assert batch[vid] == inventory.get_stock(merchant_id, vid)


def test_an_empty_request_returns_an_empty_map(
    inventory: InventoryService, merchant_id: uuid.UUID
) -> None:
    assert inventory.get_stock_map(merchant_id, []) == {}
    assert inventory.filter_available(merchant_id, []) == []


def test_a_nonsensical_quantity_is_rejected(
    inventory: InventoryService, merchant_id: uuid.UUID, variant_id
) -> None:
    for bad in (0, -1):
        with pytest.raises(ValueError, match="at least 1"):
            inventory.check_availability(merchant_id, variant_id("CASE-IP16-BLK"), bad)
        with pytest.raises(ValueError, match="at least 1"):
            inventory.filter_available(merchant_id, [variant_id("CASE-IP16-BLK")], bad)


def test_stock_reads_are_deterministic(
    inventory: InventoryService, merchant_id: uuid.UUID, variant_id
) -> None:
    vid = variant_id("CASE-IP16-BLK")
    runs = [inventory.get_stock(merchant_id, vid) for _ in range(4)]

    assert all(run == runs[0] for run in runs)


def test_a_stock_change_is_visible_immediately(
    session: Session, inventory: InventoryService, merchant_id: uuid.UUID, variant_id
) -> None:
    """RULE 12: inventory is re-checked because it changes between steps."""
    vid = variant_id("CASE-IP16-BLK")
    assert inventory.is_available(merchant_id, vid)

    row = session.execute(Inventory.__table__.select().where(Inventory.variant_id == vid)).one()
    session.get(Inventory, row.id).quantity = 0
    session.flush()

    assert not inventory.is_available(merchant_id, vid)
    assert inventory.stock_status(merchant_id, vid) is StockStatus.OUT_OF_STOCK
