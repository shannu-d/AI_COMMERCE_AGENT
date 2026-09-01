"""The Order Service against a real PostgreSQL (M10; ADR-011, ADR-013).

M10's exit condition is *a duplicate request produces exactly one logical order*,
and it is asserted three ways: the service returns the stored answer, the
database holds one row, and `orders.idempotency_key_id UNIQUE` would refuse a
second even if every application check were bypassed. Application logic makes the
common case pleasant; the constraint makes the rare case correct.

These need a live database and could not be written otherwise. The freshness
rules — live prices, locked inventory rows — are the whole point of the order
transaction, and a fake would let them pass while proving nothing.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db.models.session import Session as SessionRow
from app.domain.commerce import CartStatus, IdempotencyStatus, OrderStatus
from app.payments.money import to_minor_units
from app.services.approval_service import ApprovalService
from app.services.cart_service import CartService
from app.services.order_service import OrderError, OrderService

pytestmark = pytest.mark.requires_db

LIMIT = Decimal("10000.00")


@pytest.fixture
def carts(session: Session) -> CartService:
    return CartService(session)


@pytest.fixture
def approvals(session: Session) -> ApprovalService:
    return ApprovalService(session, ttl_seconds=900)


@pytest.fixture
def orders(session: Session) -> OrderService:
    return OrderService(session, spending_limit=LIMIT)


@pytest.fixture
def conversation(session: Session, merchant_id) -> SessionRow:
    row = SessionRow(merchant_id=merchant_id, intent={})
    session.add(row)
    session.flush()
    return row


@pytest.fixture
def case(catalog, merchant_id, variant_id):
    return catalog.get_variant(merchant_id, variant_id("CASE-IP16-BLK"))


@pytest.fixture
def approved(carts, approvals, merchant_id, conversation, case):
    """An approved cart and the key minted with it — the state M10 starts from."""
    cart = carts.add_item(merchant_id, conversation.id, case.id, 1)
    approval = approvals.approve(conversation.id, cart, cart_version=cart.version)
    key = approvals.idempotency_key_for(cart.id, approval.cart_version)
    assert key is not None, "the approval must mint a key (ADR-013)"
    return cart, approval, key


def place(orders, merchant_id, conversation, cart, key):
    return orders.create_order(
        merchant_id=merchant_id,
        session_id=conversation.id,
        cart_id=cart.id,
        cart_version=cart.version,
        idempotency_key=key,
    )


# --------------------------------------------------------------------------
# The happy path
# --------------------------------------------------------------------------


def test_an_approved_cart_becomes_an_order(orders, merchant_id, conversation, approved):
    cart, _, key = approved

    result = place(orders, merchant_id, conversation, cart, key)

    assert result.status is OrderStatus.ORDER_CREATED
    assert result.total_amount == cart.total
    assert result.replayed is False


def test_the_order_records_the_minor_unit_integer(orders, merchant_id, conversation, approved):
    """ADR-008. Computed once here, so what was recorded and what will be
    charged cannot diverge."""
    cart, _, key = approved

    result = place(orders, merchant_id, conversation, cart, key)

    assert result.total_amount_minor == to_minor_units(cart.total, cart.currency)


def test_the_order_has_no_razorpay_id_yet(session, orders, merchant_id, conversation, approved):
    """ADR-011: the internal order is committed *before* the provider is called.

    An order in ORDER_CREATED with a null `razorpay_order_id` is the state the
    ADR designs for, not a broken one. The reverse ordering would allow a
    provider order with no local record, which is unreconcilable.
    """
    cart, _, key = approved

    result = place(orders, merchant_id, conversation, cart, key)

    row = orders.get(merchant_id, result.order_id)
    assert row.razorpay_order_id is None
    assert row.status == OrderStatus.ORDER_CREATED.value


def test_order_lines_snapshot_the_catalog(
    session, orders, merchant_id, conversation, approved, case
):
    """An order line is an immutable financial record: renaming a product must
    not rewrite what somebody bought."""
    cart, _, key = approved
    result = place(orders, merchant_id, conversation, cart, key)

    session.execute(
        text("UPDATE products SET name = 'Renamed' WHERE id = :p"), {"p": case.product_id}
    )

    stored = session.execute(
        text("SELECT sku, product_name, unit_price FROM order_items WHERE order_id = :o"),
        {"o": result.order_id},
    ).one()
    assert stored.sku == case.sku
    assert stored.product_name != "Renamed"
    assert stored.unit_price == case.price


def test_the_cart_is_closed_once_ordered(carts, orders, merchant_id, conversation, approved):
    cart, _, key = approved

    place(orders, merchant_id, conversation, cart, key)

    assert carts.get(merchant_id, cart.id).status is CartStatus.ORDERED


# --------------------------------------------------------------------------
# M10's exit condition: one logical order per key
# --------------------------------------------------------------------------


def test_a_duplicate_request_returns_the_first_answer(orders, merchant_id, conversation, approved):
    """P§15, P§34. The same answer, not a new order."""
    cart, _, key = approved

    first = place(orders, merchant_id, conversation, cart, key)
    second = place(orders, merchant_id, conversation, cart, key)

    assert second.order_id == first.order_id
    assert second.total_amount == first.total_amount
    assert second.replayed is True
    assert first.replayed is False


def test_a_duplicate_request_creates_exactly_one_row(
    session, orders, merchant_id, conversation, approved
):
    cart, _, key = approved

    place(orders, merchant_id, conversation, cart, key)
    place(orders, merchant_id, conversation, cart, key)

    count = session.execute(
        text("SELECT count(*) FROM orders WHERE cart_id = :c"), {"c": cart.id}
    ).scalar_one()
    assert count == 1


def test_the_database_refuses_a_second_order_under_one_key(
    session, orders, merchant_id, conversation, approved
):
    """The constraint underneath the application logic (ADR-013).

    Two concurrent requests cannot both create an order under one key even if
    both passed every application check, because the second insert violates
    `orders.idempotency_key_id UNIQUE`.
    """
    from sqlalchemy.exc import IntegrityError

    cart, _, key = approved
    result = place(orders, merchant_id, conversation, cart, key)
    row = orders.get(merchant_id, result.order_id)

    with pytest.raises(IntegrityError):
        session.execute(
            text(
                "INSERT INTO orders (merchant_id, session_id, cart_id, cart_version,"
                " approval_id, idempotency_key_id, status, currency, subtotal_amount,"
                " total_amount, total_amount_minor) VALUES (:m, :s, :c, 1, :a, :k,"
                " 'ORDER_CREATED', 'INR', 1, 1, 100)"
            ),
            {
                "m": merchant_id,
                "s": conversation.id,
                "c": cart.id,
                "a": row.approval_id,
                "k": row.idempotency_key_id,
            },
        )
        session.flush()


def test_the_key_is_completed_and_stores_the_answer(
    session, orders, merchant_id, conversation, approved
):
    """The snapshot is what a replay returns, and money is stored as a string so
    a replay produces the same `Decimal` rather than one rebuilt from a float."""
    cart, _, key = approved
    result = place(orders, merchant_id, conversation, cart, key)

    row = session.execute(
        text("SELECT status, response_snapshot FROM idempotency_keys WHERE key = :k"),
        {"k": key},
    ).one()
    assert row.status == IdempotencyStatus.COMPLETED.value
    assert row.response_snapshot["order_id"] == str(result.order_id)
    assert isinstance(row.response_snapshot["total_amount"], str)


def test_an_unknown_key_is_refused(orders, merchant_id, conversation, approved):
    """The backend mints keys; a client-invented one protects nothing."""
    cart, _, _ = approved

    with pytest.raises(OrderError) as error:
        place(orders, merchant_id, conversation, cart, str(uuid.uuid4()))

    assert error.value.code == "VALIDATION_ERROR"


def test_a_key_from_another_session_is_refused(
    orders, merchant_id, session, approved, conversation
):
    cart, _, key = approved
    other = SessionRow(merchant_id=merchant_id, intent={})
    session.add(other)
    session.flush()

    with pytest.raises(OrderError):
        orders.create_order(
            merchant_id=merchant_id,
            session_id=other.id,
            cart_id=cart.id,
            cart_version=cart.version,
            idempotency_key=key,
        )


# --------------------------------------------------------------------------
# Policy refusals reach the caller, and no order is created
# --------------------------------------------------------------------------


def test_a_price_change_refuses_the_order(
    session, carts, orders, merchant_id, conversation, approved, case
):
    """The flagship scenario, end to end. The price moved after approval, so the
    live total no longer matches and nothing is created."""
    cart, _, key = approved
    session.execute(
        text("UPDATE product_variants SET price = price + 500 WHERE id = :i"), {"i": case.id}
    )

    with pytest.raises(OrderError) as error:
        place(orders, merchant_id, conversation, cart, key)

    assert error.value.code == "POLICY_FAILED"
    assert "PRICE_CHANGED" in error.value.details["reason_codes"]
    assert (
        session.execute(
            text("SELECT count(*) FROM orders WHERE cart_id = :c"), {"c": cart.id}
        ).scalar_one()
        == 0
    )


def test_the_refusal_carries_the_new_total(
    session, orders, merchant_id, conversation, approved, case
):
    """P§7: the number that caused the refusal is the number the buyer must be
    shown, so the recovery flow needs no second query."""
    cart, _, key = approved
    session.execute(
        text("UPDATE product_variants SET price = price + 500 WHERE id = :i"), {"i": case.id}
    )

    with pytest.raises(OrderError) as error:
        place(orders, merchant_id, conversation, cart, key)

    assert error.value.details["validated_total"] == str(case.price + Decimal("500"))


def test_stock_disappearing_after_approval_refuses_the_order(
    session, orders, merchant_id, conversation, approved, case
):
    """Read from the locked row at evaluation time, not from anything cached."""
    cart, _, key = approved
    session.execute(text("UPDATE inventory SET quantity = 0 WHERE variant_id = :i"), {"i": case.id})

    with pytest.raises(OrderError) as error:
        place(orders, merchant_id, conversation, cart, key)

    assert "OUT_OF_STOCK" in error.value.details["reason_codes"]


def test_an_unapproved_cart_cannot_become_an_order(
    session, carts, orders, merchant_id, conversation, approved, case
):
    """Rule 1, and the schema's own `approval_id NOT NULL` behind it."""
    cart, _, key = approved
    # Mutating the cart supersedes the approval (ADR-007).
    carts.add_item(merchant_id, conversation.id, case.id, 1)

    with pytest.raises(OrderError) as error:
        place(orders, merchant_id, conversation, cart, key)

    assert error.value.code == "POLICY_FAILED"


def test_a_refused_order_marks_the_key_failed(
    session, orders, merchant_id, conversation, approved, case
):
    """A FAILED key is terminal: the buyer obtains a fresh approval, which mints
    a fresh key. The same recovery path as price drift and payment failure, so
    there is one flow rather than three (ADR-013)."""
    cart, _, key = approved
    session.execute(
        text("UPDATE product_variants SET price = price + 500 WHERE id = :i"), {"i": case.id}
    )

    with pytest.raises(OrderError):
        place(orders, merchant_id, conversation, cart, key)

    status = session.execute(
        text("SELECT status FROM idempotency_keys WHERE key = :k"), {"k": key}
    ).scalar_one()
    assert status == IdempotencyStatus.FAILED.value


def test_a_failed_key_is_never_retried(session, orders, merchant_id, conversation, approved, case):
    cart, _, key = approved
    session.execute(
        text("UPDATE product_variants SET price = price + 500 WHERE id = :i"), {"i": case.id}
    )
    with pytest.raises(OrderError):
        place(orders, merchant_id, conversation, cart, key)

    # Even with the price restored, the spent key cannot be reused.
    session.execute(
        text("UPDATE product_variants SET price = price - 500 WHERE id = :i"), {"i": case.id}
    )

    with pytest.raises(OrderError) as error:
        place(orders, merchant_id, conversation, cart, key)

    assert error.value.code == "APPROVAL_REQUIRED"


def test_the_spending_limit_refuses_a_large_order(
    session, carts, approvals, merchant_id, conversation, case
):
    """P§13's ceiling, with the limit stated here rather than taken from the
    production configuration."""
    cart = carts.add_item(merchant_id, conversation.id, case.id, 3)
    approval = approvals.approve(conversation.id, cart, cart_version=cart.version)
    key = approvals.idempotency_key_for(cart.id, approval.cart_version)
    strict = OrderService(session, spending_limit=Decimal("100.00"))

    with pytest.raises(OrderError) as error:
        strict.create_order(
            merchant_id=merchant_id,
            session_id=conversation.id,
            cart_id=cart.id,
            cart_version=cart.version,
            idempotency_key=key,
        )

    assert "SPENDING_LIMIT_EXCEEDED" in error.value.details["reason_codes"]


# --------------------------------------------------------------------------
# Nothing from the client is authoritative
# --------------------------------------------------------------------------


def test_create_order_accepts_no_amount():
    """F§17's forged amount has nowhere to be submitted (ADR-011).

    Asserted on the signature: a method that ignored an amount would still be a
    method somebody believed they had used.
    """
    import inspect

    parameters = set(inspect.signature(OrderService.create_order).parameters)

    assert parameters == {
        "self",
        "merchant_id",
        "session_id",
        "cart_id",
        "cart_version",
        "idempotency_key",
    }


def test_a_claimed_cart_version_is_checked_not_obeyed(orders, merchant_id, conversation, approved):
    """`cart_version` is a claim. Sending the wrong one refuses the order rather
    than ordering some other version."""
    cart, _, key = approved

    with pytest.raises(OrderError) as error:
        orders.create_order(
            merchant_id=merchant_id,
            session_id=conversation.id,
            cart_id=cart.id,
            cart_version=cart.version + 5,
            idempotency_key=key,
        )

    assert error.value.code == "POLICY_FAILED"
    assert "INVALID_CART" in error.value.details["reason_codes"]
