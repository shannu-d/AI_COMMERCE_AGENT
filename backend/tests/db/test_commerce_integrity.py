"""M6's exit tests: the commerce schema against a real PostgreSQL (ADR-006).

ADR-006 names them, and they are all of one kind — *the database refuses*. That
is the point of the milestone. Every rule asserted here could have been written
as a service check instead, and each one that had been would be a rule some
future code path forgets. A constraint is not forgettable.

The load-bearing assertion is `test_an_order_cannot_be_stored_without_an_approval`.
`orders.approval_id NOT NULL` is the architecture's central invariant expressed
as a column definition: **the database itself refuses to store an unapproved
order.** Everything else in the money path — the Policy Engine, the approval
lifecycle, the idempotency key — is defence in front of that line.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import Session

from app.db.models import (
    Approval,
    AuditEvent,
    Cart,
    CartItem,
    IdempotencyKey,
    Order,
    OrderItem,
    Payment,
    WebhookEvent,
)
from app.db.models.session import Session as SessionRow
from app.domain.commerce import (
    ApprovalStatus,
    AuditActor,
    AuditEventType,
    CartStatus,
    IdempotencyScope,
    OrderStatus,
    PaymentStatus,
)

pytestmark = pytest.mark.requires_db

FINGERPRINT = "a" * 64
LATER = datetime.now(UTC) + timedelta(hours=1)


# --------------------------------------------------------------------------
# Builders
#
# Deliberately explicit rather than factory-generated: an order needs a session,
# a cart, an approval and an idempotency key before it can exist, and reading
# that chain in the fixture is reading the invariant.
# --------------------------------------------------------------------------


@pytest.fixture
def conversation(session: Session, merchant_id) -> SessionRow:
    row = SessionRow(merchant_id=merchant_id, intent={})
    session.add(row)
    session.flush()
    return row


@pytest.fixture
def cart(session: Session, merchant_id, conversation) -> Cart:
    row = Cart(
        merchant_id=merchant_id,
        session_id=conversation.id,
        status=CartStatus.ACTIVE.value,
        currency="INR",
        subtotal_amount=Decimal("999.00"),
        total_amount=Decimal("999.00"),
    )
    session.add(row)
    session.flush()
    return row


@pytest.fixture
def approval(session: Session, conversation, cart) -> Approval:
    row = Approval(
        session_id=conversation.id,
        cart_id=cart.id,
        cart_version=cart.version,
        approved_total=Decimal("999.00"),
        currency="INR",
        items_fingerprint=FINGERPRINT,
        status=ApprovalStatus.APPROVED.value,
        approved_at=datetime.now(UTC),
        expires_at=LATER,
    )
    session.add(row)
    session.flush()
    return row


@pytest.fixture
def key(session: Session, conversation, cart) -> IdempotencyKey:
    row = IdempotencyKey(
        key=f"key-{uuid.uuid4()}",
        scope=IdempotencyScope.ORDER_CREATION.value,
        session_id=conversation.id,
        cart_id=cart.id,
        cart_version=cart.version,
        approved_total=Decimal("999.00"),
        currency="INR",
        expires_at=LATER,
    )
    session.add(row)
    session.flush()
    return row


def make_order(session, merchant_id, conversation, cart, approval, key, **overrides) -> Order:
    fields = {
        "status": OrderStatus.ORDER_CREATED.value,
        "currency": "INR",
        "subtotal_amount": Decimal("999.00"),
        "total_amount": Decimal("999.00"),
        "total_amount_minor": 99900,
        **overrides,
    }
    row = Order(
        merchant_id=merchant_id,
        session_id=conversation.id,
        cart_id=cart.id,
        cart_version=cart.version,
        approval_id=approval.id,
        idempotency_key_id=key.id,
        **fields,
    )
    session.add(row)
    session.flush()
    return row


# --------------------------------------------------------------------------
# The invariant
# --------------------------------------------------------------------------


def test_an_order_cannot_be_stored_without_an_approval(
    session, merchant_id, conversation, cart, key
):
    """ADR-006's named M6 test, and the one that matters most.

    Not a service rule, not a policy check — a `NOT NULL` column. There is no
    code path, reviewed or otherwise, that can put an unapproved order in this
    database.
    """
    order = Order(
        merchant_id=merchant_id,
        session_id=conversation.id,
        cart_id=cart.id,
        cart_version=cart.version,
        approval_id=None,
        idempotency_key_id=key.id,
        currency="INR",
        subtotal_amount=Decimal("999.00"),
        total_amount=Decimal("999.00"),
        total_amount_minor=99900,
    )
    session.add(order)

    with pytest.raises(IntegrityError):
        session.flush()


def test_an_order_with_a_real_approval_is_stored(
    session, merchant_id, conversation, cart, approval, key
):
    """The constraint permits the legitimate case, which is the other half of
    proving it is a constraint and not a bug."""
    order = make_order(session, merchant_id, conversation, cart, approval, key)

    assert order.id is not None
    assert order.approval_id == approval.id


# --------------------------------------------------------------------------
# Partial unique indexes
# --------------------------------------------------------------------------


def test_a_session_may_have_only_one_active_cart(session, merchant_id, conversation, cart):
    second = Cart(
        merchant_id=merchant_id,
        session_id=conversation.id,
        status=CartStatus.ACTIVE.value,
        currency="INR",
    )
    session.add(second)

    with pytest.raises(IntegrityError):
        session.flush()


def test_a_session_may_have_many_finished_carts(session, merchant_id, conversation, cart):
    """The index is *partial* on purpose: a session accumulates ORDERED and
    ABANDONED carts over its life and only the live one is exclusive."""
    cart.status = CartStatus.ORDERED.value
    session.flush()

    for status in (CartStatus.ORDERED, CartStatus.ABANDONED):
        session.add(
            Cart(
                merchant_id=merchant_id,
                session_id=conversation.id,
                status=status.value,
                currency="INR",
            )
        )
    session.flush()

    count = session.execute(
        text("SELECT count(*) FROM carts WHERE session_id = :sid"), {"sid": conversation.id}
    ).scalar_one()
    assert count == 3


def test_a_cart_version_can_be_approved_only_once(session, conversation, cart, approval):
    duplicate = Approval(
        session_id=conversation.id,
        cart_id=cart.id,
        cart_version=cart.version,
        approved_total=Decimal("999.00"),
        currency="INR",
        items_fingerprint=FINGERPRINT,
        status=ApprovalStatus.APPROVED.value,
        approved_at=datetime.now(UTC),
        expires_at=LATER,
    )
    session.add(duplicate)

    with pytest.raises(IntegrityError):
        session.flush()


def test_superseded_approvals_for_one_version_are_kept(session, conversation, cart, approval):
    """ADR-014's price-drift recovery needs the *history* of approvals for a
    cart, not just its latest state. The partial index is what allows that."""
    approval.status = ApprovalStatus.SUPERSEDED.value
    session.flush()

    replacement = Approval(
        session_id=conversation.id,
        cart_id=cart.id,
        cart_version=cart.version,
        approved_total=Decimal("1199.00"),
        currency="INR",
        items_fingerprint=FINGERPRINT,
        status=ApprovalStatus.APPROVED.value,
        approved_at=datetime.now(UTC),
        expires_at=LATER,
    )
    session.add(replacement)
    session.flush()
    approval.superseded_by_id = replacement.id
    session.flush()

    assert approval.superseded_by_id == replacement.id


def test_an_approved_row_must_carry_a_timestamp(session, conversation, cart):
    """An authorization nobody can date is not much of an audit record."""
    session.add(
        Approval(
            session_id=conversation.id,
            cart_id=cart.id,
            cart_version=cart.version,
            approved_total=Decimal("999.00"),
            currency="INR",
            items_fingerprint=FINGERPRINT,
            status=ApprovalStatus.APPROVED.value,
            approved_at=None,
            expires_at=LATER,
        )
    )

    with pytest.raises(IntegrityError):
        session.flush()


# --------------------------------------------------------------------------
# Webhook deduplication
# --------------------------------------------------------------------------


def _webhook(event_id: str, **overrides) -> WebhookEvent:
    return WebhookEvent(
        event_id=event_id,
        event_type="payment.captured",
        signature="sig",
        raw_body='{"event":"payment.captured"}',
        payload={"event": "payment.captured"},
        **overrides,
    )


def test_the_same_event_cannot_be_recorded_twice(session):
    """P§25, P§26. Enforced by the database, so two concurrent deliveries of one
    event cannot both proceed — which a read-then-write check cannot promise."""
    session.add(_webhook("evt_duplicate"))
    session.flush()
    session.add(_webhook("evt_duplicate"))

    with pytest.raises(IntegrityError):
        session.flush()


def test_two_different_events_are_both_recorded(session):
    session.add(_webhook("evt_one"))
    session.add(_webhook("evt_two"))
    session.flush()

    count = session.execute(
        text("SELECT count(*) FROM webhook_events WHERE event_id IN ('evt_one', 'evt_two')")
    ).scalar_one()
    assert count == 2


def test_an_event_may_arrive_before_its_order_is_known(session):
    """P§27: `order_id` is nullable because refusing to record an unmatched
    event would lose the only copy of it."""
    event = _webhook("evt_orphan")
    session.add(event)
    session.flush()

    assert event.order_id is None


# --------------------------------------------------------------------------
# Foreign keys reject orphans
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("table", "columns", "values"),
    [
        (
            "carts",
            "(merchant_id, session_id, status, currency)",
            "(gen_random_uuid(), gen_random_uuid(), 'ACTIVE', 'INR')",
        ),
        (
            "cart_items",
            "(cart_id, variant_id, quantity, unit_price_snapshot, line_total, currency)",
            "(gen_random_uuid(), gen_random_uuid(), 1, 1, 1, 'INR')",
        ),
        (
            "payments",
            "(order_id, razorpay_payment_id, status, amount, amount_minor, currency)",
            "(gen_random_uuid(), 'pay_orphan', 'CAPTURED', 1, 100, 'INR')",
        ),
        (
            "order_items",
            "(order_id, variant_id, sku, product_name, variant_name, quantity, unit_price,"
            " line_total, currency)",
            "(gen_random_uuid(), gen_random_uuid(), 'X', 'X', 'X', 1, 1, 1, 'INR')",
        ),
    ],
)
def test_a_foreign_key_rejects_an_orphan(session, table, columns, values):
    """Every row in the money path points at something that exists."""
    with pytest.raises((IntegrityError, DBAPIError)):
        session.execute(text(f"INSERT INTO {table} {columns} VALUES {values}"))
        session.flush()


def test_a_variant_in_a_placed_order_cannot_be_deleted(
    session, merchant_id, conversation, cart, approval, key, variant_id
):
    """RESTRICT, not CASCADE. The financial record outlives the catalog row: an
    order line must still show what was bought after a product is withdrawn."""
    order = make_order(session, merchant_id, conversation, cart, approval, key)
    vid = variant_id("CASE-IP16-BLK")
    session.add(
        OrderItem(
            order_id=order.id,
            variant_id=vid,
            sku="CASE-IP16-BLK",
            product_name="AeroCase Pro",
            variant_name="Black",
            quantity=1,
            unit_price=Decimal("999.00"),
            line_total=Decimal("999.00"),
            currency="INR",
        )
    )
    session.flush()

    with pytest.raises((IntegrityError, DBAPIError)):
        session.execute(text("DELETE FROM product_variants WHERE id = :id"), {"id": vid})
        session.flush()


# --------------------------------------------------------------------------
# Uniqueness elsewhere in the money path
# --------------------------------------------------------------------------


def test_one_order_per_idempotency_key(session, merchant_id, conversation, cart, approval, key):
    """ADR-013. The whole point of the key is that it cannot produce two orders."""
    make_order(session, merchant_id, conversation, cart, approval, key)
    second = Order(
        merchant_id=merchant_id,
        session_id=conversation.id,
        cart_id=cart.id,
        cart_version=cart.version,
        approval_id=approval.id,
        idempotency_key_id=key.id,
        currency="INR",
        subtotal_amount=Decimal("999.00"),
        total_amount=Decimal("999.00"),
        total_amount_minor=99900,
    )
    session.add(second)

    with pytest.raises(IntegrityError):
        session.flush()


def test_a_razorpay_order_id_maps_to_at_most_one_order(
    session, merchant_id, conversation, cart, approval, key
):
    make_order(
        session, merchant_id, conversation, cart, approval, key, razorpay_order_id="order_XYZ"
    )
    other_key = IdempotencyKey(
        key=f"key-{uuid.uuid4()}",
        scope=IdempotencyScope.ORDER_CREATION.value,
        session_id=conversation.id,
        cart_id=cart.id,
        cart_version=cart.version,
        approved_total=Decimal("999.00"),
        currency="INR",
        expires_at=LATER,
    )
    session.add(other_key)
    session.flush()

    with pytest.raises(IntegrityError):
        make_order(
            session,
            merchant_id,
            conversation,
            cart,
            approval,
            other_key,
            razorpay_order_id="order_XYZ",
        )


def test_a_cart_holds_one_line_per_variant(session, cart, variant_id):
    vid = variant_id("CASE-IP16-BLK")
    for _ in range(2):
        session.add(
            CartItem(
                cart_id=cart.id,
                variant_id=vid,
                quantity=1,
                unit_price_snapshot=Decimal("999.00"),
                line_total=Decimal("999.00"),
                currency="INR",
            )
        )

    with pytest.raises(IntegrityError):
        session.flush()


# --------------------------------------------------------------------------
# The audit log
# --------------------------------------------------------------------------


def test_audit_events_are_totally_ordered_even_within_one_transaction(session, conversation):
    """`seq` exists because timestamps tie. Two events written in the same
    transaction can share a microsecond, and "what happened next" is the question
    an audit asks."""
    for event_type in (AuditEventType.CART_CREATED, AuditEventType.USER_APPROVED):
        session.add(
            AuditEvent(
                event_type=event_type.value,
                actor=AuditActor.USER.value,
                session_id=conversation.id,
                payload={},
            )
        )
    session.flush()

    rows = (
        session.execute(
            text("SELECT seq FROM audit_events WHERE session_id = :sid ORDER BY seq"),
            {"sid": conversation.id},
        )
        .scalars()
        .all()
    )
    assert len(rows) == 2
    assert rows[0] < rows[1]


def test_an_audit_event_may_name_none_of_the_four_entities(session):
    """Not every event has a cart, an order or a payment. A signature rejection
    has none of them and still has to be recorded."""
    session.add(
        AuditEvent(
            event_type=AuditEventType.WEBHOOK_SIGNATURE_REJECTED.value,
            actor=AuditActor.RAZORPAY.value,
            payload={"reason": "signature mismatch"},
        )
    )
    session.flush()


def test_an_unknown_audit_event_type_is_refused(session):
    """The CHECK is rendered from `AuditEventType`, so the database and the
    application cannot disagree about the vocabulary."""
    with pytest.raises((IntegrityError, DBAPIError)):
        session.execute(
            text(
                "INSERT INTO audit_events (event_type, actor, payload) "
                "VALUES ('SOMETHING_HAPPENED', 'SYSTEM', '{}'::jsonb)"
            )
        )
        session.flush()


# --------------------------------------------------------------------------
# Money
# --------------------------------------------------------------------------


def test_money_round_trips_as_decimal(session, merchant_id, conversation, cart, approval, key):
    """ADR-008. No float touches this path at any point."""
    order = make_order(
        session,
        merchant_id,
        conversation,
        cart,
        approval,
        key,
        total_amount=Decimal("1500.10"),
        total_amount_minor=150010,
    )
    session.expire(order)

    assert order.total_amount == Decimal("1500.10")
    assert isinstance(order.total_amount, Decimal)
    assert order.total_amount_minor == 150010


@pytest.mark.parametrize(
    ("table", "columns", "values"),
    [
        (
            "carts",
            "(merchant_id, session_id, status, currency, total_amount)",
            "(gen_random_uuid(), gen_random_uuid(), 'ACTIVE', 'INR', -1)",
        ),
        (
            "payments",
            "(order_id, razorpay_payment_id, status, amount, amount_minor, currency)",
            "(gen_random_uuid(), 'pay_neg', 'CAPTURED', -1, 100, 'INR')",
        ),
    ],
)
def test_no_negative_amount_is_storable(session, table, columns, values):
    with pytest.raises((IntegrityError, DBAPIError)):
        session.execute(text(f"INSERT INTO {table} {columns} VALUES {values}"))
        session.flush()


def test_a_payment_status_outside_the_enum_is_refused(session):
    with pytest.raises((IntegrityError, DBAPIError)):
        session.execute(
            text(
                "INSERT INTO payments (order_id, razorpay_payment_id, status, amount,"
                " amount_minor, currency) VALUES (gen_random_uuid(), 'pay_x', 'SETTLED',"
                " 1, 100, 'INR')"
            )
        )
        session.flush()


def test_every_payment_status_in_the_enum_is_accepted(session):
    """The other direction: the CHECK must not be narrower than the enum, or a
    legitimate provider status would be unstorable."""
    from app.domain.commerce import PAYMENT_STATUSES

    assert set(PAYMENT_STATUSES) == {member.value for member in PaymentStatus}
    rendered = session.execute(
        text(
            "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
            "WHERE conname = 'ck_payments_status_is_known'"
        )
    ).scalar_one()
    for status in PAYMENT_STATUSES:
        assert f"'{status}'" in rendered


def test_a_payment_row_can_be_written_for_a_real_order(
    session, merchant_id, conversation, cart, approval, key
):
    order = make_order(session, merchant_id, conversation, cart, approval, key)
    session.add(
        Payment(
            order_id=order.id,
            razorpay_payment_id="pay_real",
            status=PaymentStatus.CAPTURED.value,
            amount=Decimal("999.00"),
            amount_minor=99900,
            currency="INR",
        )
    )
    session.flush()
