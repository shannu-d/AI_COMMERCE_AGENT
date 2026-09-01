"""The audit log (M13; ADR-006, A§39, A§40, RZP-07).

M13's exit condition is *a full transaction is reconstructable from audit
events*, and the test that proves it walks a whole purchase — cart, approval,
policy, order, provider order, webhook — and then reads the story back from the
log alone, without touching any other table.

The rest is about the two properties an audit log either has or is not worth
keeping: it is append-only, and it attributes each event to whoever actually
caused it. `USER_APPROVED` is written with actor `USER` and nothing else, because
that row is the record that a human authorized a payment.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from decimal import Decimal

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db.models.session import Session as SessionRow
from app.domain.commerce import AuditActor, AuditEventType
from app.repositories.audit_repository import AuditRepository
from app.services.approval_service import ApprovalService
from app.services.audit_service import AuditService
from app.services.cart_service import CartService
from app.services.order_service import OrderError, OrderService

pytestmark = pytest.mark.requires_db

WEBHOOK_SECRET = "whsec_audit_test"


@pytest.fixture
def audit(session: Session) -> AuditService:
    return AuditService(session)


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
def placed_order(session, merchant_id, conversation, case):
    """A real order, because `audit_events.order_id` is a foreign key."""
    from app.db.models import Order

    carts = CartService(session)
    approvals = ApprovalService(session, ttl_seconds=900)
    cart = carts.add_item(merchant_id, conversation.id, case.id, 1)
    approval = approvals.approve(conversation.id, cart, cart_version=cart.version)
    key = approvals.idempotency_key_for(cart.id, approval.cart_version)
    result = OrderService(session, spending_limit=Decimal("10000.00")).create_order(
        merchant_id=merchant_id,
        session_id=conversation.id,
        cart_id=cart.id,
        cart_version=cart.version,
        idempotency_key=key,
    )
    return session.get(Order, result.order_id)


def events_for_cart(session, cart_id):
    return AuditRepository(session).for_cart(cart_id)


def types_of(events):
    return [event.event_type for event in events]


# --------------------------------------------------------------------------
# M13's exit condition
# --------------------------------------------------------------------------


def test_a_whole_purchase_is_reconstructable_from_the_log(
    session, merchant_id, conversation, case, audit
):
    """The milestone's exit condition, walked end to end.

    Everything below is read back from `audit_events` alone. If the story is
    incomplete here, it is incomplete for whoever has to explain a charge to a
    buyer months from now.
    """
    from app.db.models import Order
    from app.payments import RazorpayClient
    from app.services.webhook_service import WebhookService
    from tests.fixtures.razorpay import FakeRazorpayApi, order_response

    carts = CartService(session)
    approvals = ApprovalService(session, ttl_seconds=900)

    cart = carts.add_item(merchant_id, conversation.id, case.id, 1)
    approval = approvals.approve(conversation.id, cart, cart_version=cart.version)
    key = approvals.idempotency_key_for(cart.id, approval.cart_version)

    result = OrderService(session, spending_limit=Decimal("10000.00")).create_order(
        merchant_id=merchant_id,
        session_id=conversation.id,
        cart_id=cart.id,
        cart_version=cart.version,
        idempotency_key=key,
    )

    api = FakeRazorpayApi(order_response(amount=result.total_amount_minor))
    client = RazorpayClient(api, key_id="rzp_test_public", merchant_name="CircuitCraft")
    OrderService(session, spending_limit=Decimal("10000.00")).attach_provider_order(
        merchant_id, result.order_id, client
    )
    order = session.get(Order, result.order_id)

    body = json.dumps(
        {
            "id": "evt_story",
            "event": "payment.captured",
            "payload": {
                "payment": {
                    "entity": {
                        "id": "pay_story",
                        "order_id": order.razorpay_order_id,
                        "amount": order.total_amount_minor,
                        "currency": "INR",
                    }
                }
            },
        },
        separators=(",", ":"),
    ).encode("utf-8")
    signature = hmac.new(WEBHOOK_SECRET.encode(), body, hashlib.sha256).hexdigest()
    WebhookService(session).process(body, signature, WEBHOOK_SECRET)

    # The whole story, from the log and nothing else.
    story = types_of(events_for_cart(session, cart.id)) + [
        row["event_type"] for row in audit.reconstruct_order(result.order_id)
    ]

    for required in (
        AuditEventType.CART_CREATED,
        AuditEventType.USER_APPROVED,
        AuditEventType.POLICY_PASS,
        AuditEventType.ORDER_CREATED,
        AuditEventType.RAZORPAY_ORDER_CREATED,
        AuditEventType.PAYMENT_WEBHOOK_RECEIVED,
        AuditEventType.PAYMENT_CONFIRMED,
    ):
        assert required.value in story, f"{required.value} missing from the reconstruction"


def test_the_reconstruction_is_ordered_by_seq(session, audit, placed_order):
    """`seq`, never `created_at`: events written in one transaction share a
    timestamp, and an audit read back in an ambiguous order cannot answer the
    question it exists for.

    The order id is a real one because `audit_events.order_id` is a foreign key
    - an audit row pointing at an order that never existed would be a record of
    nothing, and the schema refuses it.
    """
    for _ in range(3):
        audit.checkout_started(placed_order.id)

    rows = audit.reconstruct_order(placed_order.id)

    assert [row["seq"] for row in rows] == sorted(row["seq"] for row in rows)
    assert len(rows) >= 3


# --------------------------------------------------------------------------
# Append-only
# --------------------------------------------------------------------------


def test_the_repository_has_no_way_to_change_a_row():
    """ADR-006. In deployment the role has INSERT and SELECT only; this is the
    same rule where a developer actually meets it."""
    methods = {name for name in dir(AuditRepository) if not name.startswith("_")}

    assert "append" in methods
    assert not any(word in name for name in methods for word in ("update", "delete", "remove"))


def test_the_audit_table_has_no_updated_at(session):
    columns = (
        session.execute(
            text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name = 'audit_events'"
            )
        )
        .scalars()
        .all()
    )

    assert "updated_at" not in columns


def test_an_unknown_event_type_cannot_be_appended(session, audit):
    """Typed on the enum, so a value nobody defined cannot be written and then
    discovered later by whoever reads the log."""
    with pytest.raises((AttributeError, ValueError, TypeError)):
        AuditRepository(session).append("SOMETHING_HAPPENED", AuditActor.SYSTEM)  # type: ignore[arg-type]


# --------------------------------------------------------------------------
# Attribution
# --------------------------------------------------------------------------


def test_an_approval_is_attributed_to_the_user(session, merchant_id, conversation, case):
    """The single most important row in the log. `AGENT` here would make the log
    disagree with the architecture it evidences (ADR-007)."""
    carts = CartService(session)
    approvals = ApprovalService(session, ttl_seconds=900)
    cart = carts.add_item(merchant_id, conversation.id, case.id, 1)

    approvals.approve(conversation.id, cart, cart_version=cart.version)

    approved = [
        event
        for event in events_for_cart(session, cart.id)
        if event.event_type == AuditEventType.USER_APPROVED.value
    ]
    assert len(approved) == 1
    assert approved[0].actor == AuditActor.USER.value


def test_a_cart_is_attributed_to_the_agent(session, merchant_id, conversation, case):
    cart = CartService(session).add_item(merchant_id, conversation.id, case.id, 1)

    created = [
        event
        for event in events_for_cart(session, cart.id)
        if event.event_type == AuditEventType.CART_CREATED.value
    ]
    assert created[0].actor == AuditActor.AGENT.value


def test_a_payment_is_attributed_to_the_provider(session, audit, placed_order):
    audit.payment_confirmed(placed_order.id, payment_id=None, razorpay_payment_id="pay_x")

    confirmed = [
        row
        for row in audit.reconstruct_order(placed_order.id)
        if row["event_type"] == AuditEventType.PAYMENT_CONFIRMED.value
    ]
    assert confirmed[0]["actor"] == AuditActor.RAZORPAY.value


# --------------------------------------------------------------------------
# The four events beyond RZP-07's twelve
# --------------------------------------------------------------------------


def test_a_superseded_approval_is_recorded(session, merchant_id, conversation, case):
    """The gap ADR-007 opened and M8 recorded, now closed.

    Without this row an approval that vanished between two reads is
    unexplainable - and the price-drift scenario is precisely a story about an
    approval vanishing.
    """
    carts = CartService(session)
    approvals = ApprovalService(session, ttl_seconds=900)
    cart = carts.add_item(merchant_id, conversation.id, case.id, 1)
    approvals.approve(conversation.id, cart, cart_version=cart.version)

    carts.add_item(merchant_id, conversation.id, case.id, 1)

    superseded = [
        event
        for event in events_for_cart(session, cart.id)
        if event.event_type == AuditEventType.APPROVAL_SUPERSEDED.value
    ]
    assert superseded
    assert superseded[0].payload["reason"]


def test_a_policy_refusal_records_its_reason_codes(session, merchant_id, conversation, case):
    """A POLICY_FAIL without them records that something was refused and not
    what was wrong, which is the half a reconstruction needs."""
    carts = CartService(session)
    approvals = ApprovalService(session, ttl_seconds=900)
    cart = carts.add_item(merchant_id, conversation.id, case.id, 1)
    approval = approvals.approve(conversation.id, cart, cart_version=cart.version)
    key = approvals.idempotency_key_for(cart.id, approval.cart_version)
    session.execute(
        text("UPDATE product_variants SET price = price + 500 WHERE id = :i"), {"i": case.id}
    )

    with pytest.raises(OrderError):
        OrderService(session, spending_limit=Decimal("10000.00")).create_order(
            merchant_id=merchant_id,
            session_id=conversation.id,
            cart_id=cart.id,
            cart_version=cart.version,
            idempotency_key=key,
        )

    failures = [
        event
        for event in events_for_cart(session, cart.id)
        if event.event_type == AuditEventType.POLICY_FAIL.value
    ]
    assert "PRICE_CHANGED" in failures[0].payload["reason_codes"]


def test_a_price_change_records_both_totals(session, merchant_id, conversation, case):
    """ "The price changed" is not actionable without knowing from what, to what."""
    carts = CartService(session)
    approvals = ApprovalService(session, ttl_seconds=900)
    cart = carts.add_item(merchant_id, conversation.id, case.id, 1)
    approval = approvals.approve(conversation.id, cart, cart_version=cart.version)
    key = approvals.idempotency_key_for(cart.id, approval.cart_version)
    session.execute(
        text("UPDATE product_variants SET price = price + 500 WHERE id = :i"), {"i": case.id}
    )

    with pytest.raises(OrderError):
        OrderService(session, spending_limit=Decimal("10000.00")).create_order(
            merchant_id=merchant_id,
            session_id=conversation.id,
            cart_id=cart.id,
            cart_version=cart.version,
            idempotency_key=key,
        )

    drift = [
        event
        for event in events_for_cart(session, cart.id)
        if event.event_type == AuditEventType.PRICE_CHANGED.value
    ]
    assert drift[0].payload["previous_total"] == str(case.price)
    assert drift[0].payload["current_total"] == str(case.price + Decimal("500"))


def test_an_inventory_failure_names_the_sku_but_not_the_stock_level(
    session, merchant_id, conversation, case
):
    """ADR-009, closing E5. A merchant's position is not written into a record
    read during support."""
    carts = CartService(session)
    approvals = ApprovalService(session, ttl_seconds=900)
    cart = carts.add_item(merchant_id, conversation.id, case.id, 1)
    approval = approvals.approve(conversation.id, cart, cart_version=cart.version)
    key = approvals.idempotency_key_for(cart.id, approval.cart_version)
    session.execute(text("UPDATE inventory SET quantity = 0 WHERE variant_id = :i"), {"i": case.id})

    with pytest.raises(OrderError):
        OrderService(session, spending_limit=Decimal("10000.00")).create_order(
            merchant_id=merchant_id,
            session_id=conversation.id,
            cart_id=cart.id,
            cart_version=cart.version,
            idempotency_key=key,
        )

    failures = [
        event
        for event in events_for_cart(session, cart.id)
        if event.event_type == AuditEventType.INVENTORY_FAILURE.value
    ]
    assert failures[0].payload["sku"] == case.sku
    assert "available" not in str(failures[0].payload)


# --------------------------------------------------------------------------
# What is never written
# --------------------------------------------------------------------------


def test_no_payload_carries_a_secret(session, merchant_id, conversation, case, audit):
    """L§45, ADR-006. Identifiers, amounts, codes and statuses - never a key,
    never a signature, never a raw provider body."""
    carts = CartService(session)
    approvals = ApprovalService(session, ttl_seconds=900)
    cart = carts.add_item(merchant_id, conversation.id, case.id, 1)
    approvals.approve(conversation.id, cart, cart_version=cart.version)
    audit.webhook_signature_rejected()

    rendered = str(
        session.execute(text("SELECT payload FROM audit_events")).scalars().all()
    ).lower()

    for forbidden in ("secret", "signature", "raw_body", "sk-ant", "rzp_test", "password"):
        assert forbidden not in rendered


def test_a_rejected_signature_is_recorded_without_naming_an_order(audit, session):
    """P§23: an unverified request names nothing this application is entitled to
    believe, so the row carries no order id - and the signature itself is never
    written down."""
    event = audit.webhook_signature_rejected()

    assert event.order_id is None
    assert "signature" not in str(event.payload)
