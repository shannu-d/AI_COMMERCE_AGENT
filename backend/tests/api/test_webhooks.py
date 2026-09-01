"""The Razorpay webhook (M12; ADR-012, P§22–P§28).

M12's exit condition is *an invalid signature is rejected; a duplicate event
causes one transition*, and both are here. Neither needs a Razorpay account: the
signature is HMAC-SHA256 over the raw body with a secret this test controls, so
the whole verification path is exercisable offline. That is the difference
between M12 and M11 — M11's exit condition genuinely needs a credential, and
M12's does not.

The properties under test are the ones a network makes unavoidable: the same
event will arrive twice, events will arrive out of order, and one will arrive for
an order this system has never heard of.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.api.routes.webhooks import SIGNATURE_HEADER
from app.config import get_settings
from app.db.models.session import Session as SessionRow
from app.db.session import get_db
from app.domain.commerce import OrderStatus
from app.main import create_app

pytestmark = pytest.mark.requires_db

SECRET = "whsec_test_only_never_a_real_one"


@pytest.fixture
def api(session: Session) -> TestClient:
    """A client whose webhook secret is one this test knows.

    Overriding `get_settings` rather than mutating the environment keeps the
    secret out of the process and out of any other test.
    """
    from pydantic import SecretStr

    app = create_app()
    base = get_settings()
    configured = base.model_copy(update={"razorpay_webhook_secret": SecretStr(SECRET)})

    app.dependency_overrides[get_db] = lambda: session
    app.dependency_overrides[get_settings] = lambda: configured
    return TestClient(app)


@pytest.fixture
def paid_order(session: Session, merchant_id, variant_id):
    """An order with a provider id, waiting for a webhook to say what happened."""
    from app.services.approval_service import ApprovalService
    from app.services.cart_service import CartService
    from app.services.order_service import OrderService

    conversation = SessionRow(merchant_id=merchant_id, intent={})
    session.add(conversation)
    session.flush()

    carts = CartService(session)
    approvals = ApprovalService(session, ttl_seconds=900)
    cart = carts.add_item(merchant_id, conversation.id, variant_id("CASE-IP16-BLK"), 1)
    approval = approvals.approve(conversation.id, cart, cart_version=cart.version)
    key = approvals.idempotency_key_for(cart.id, approval.cart_version)

    result = OrderService(session, spending_limit=Decimal("10000.00")).create_order(
        merchant_id=merchant_id,
        session_id=conversation.id,
        cart_id=cart.id,
        cart_version=cart.version,
        idempotency_key=key,
    )
    from app.db.models import Order

    order = session.get(Order, result.order_id)
    order.razorpay_order_id = "order_TestModeXYZ"
    order.status = OrderStatus.RAZORPAY_ORDER_CREATED.value
    session.flush()
    return order


def signed(body: dict) -> tuple[bytes, str]:
    """A body and its correct signature."""
    raw = json.dumps(body, separators=(",", ":")).encode("utf-8")
    signature = hmac.new(SECRET.encode("utf-8"), raw, hashlib.sha256).hexdigest()
    return raw, signature


def event(
    event_type: str = "payment.captured",
    *,
    event_id: str = "evt_one",
    razorpay_order_id: str = "order_TestModeXYZ",
    payment_id: str = "pay_one",
    amount: int = 99900,
    **entity_extra,
) -> dict:
    return {
        "id": event_id,
        "event": event_type,
        "payload": {
            "payment": {
                "entity": {
                    "id": payment_id,
                    "order_id": razorpay_order_id,
                    "amount": amount,
                    "currency": "INR",
                    "method": "upi",
                    **entity_extra,
                }
            }
        },
    }


def post(api, body: dict, *, signature: str | None = None, tamper: bool = False):
    raw, correct = signed(body)
    if tamper:
        raw = raw.replace(b'"amount":', b'"amount" :')  # same JSON, different bytes
    headers = {SIGNATURE_HEADER: signature if signature is not None else correct}
    return api.post("/api/webhooks/razorpay", content=raw, headers=headers)


# --------------------------------------------------------------------------
# Verification — M12's exit condition, half one
# --------------------------------------------------------------------------


def test_a_correctly_signed_event_is_accepted(api, paid_order):
    response = post(api, event())

    assert response.status_code == 200
    assert response.json()["status"] == "processed"


def test_a_wrong_signature_is_rejected(api, paid_order):
    """P§23: an unverified webhook is not a webhook, it is an anonymous HTTP
    request."""
    response = post(api, event(), signature="0" * 64)

    assert response.status_code == 400
    assert response.json()["status"] == "rejected"


def test_a_missing_signature_is_rejected(api, paid_order):
    raw, _ = signed(event())

    response = api.post("/api/webhooks/razorpay", content=raw)

    assert response.status_code == 400


def test_a_rejected_signature_changes_no_payment_state(session, api, paid_order):
    before = paid_order.status

    post(api, event(), signature="deadbeef")

    session.expire(paid_order)
    assert paid_order.status == before
    assert (
        session.execute(
            text("SELECT count(*) FROM payments WHERE order_id = :o"), {"o": paid_order.id}
        ).scalar_one()
        == 0
    )
    assert session.execute(text("SELECT count(*) FROM webhook_events")).scalar_one() == 0


def test_a_body_altered_in_flight_is_rejected(api, paid_order):
    """The signature is over the raw bytes. Re-spacing the JSON leaves it the
    same document and a different byte sequence, which is exactly what P§24 says
    a re-serialized verification would miss."""
    response = post(api, event(), tamper=True)

    assert response.status_code == 400


def test_the_rejection_says_nothing_about_why(api, paid_order):
    """A caller probing for a valid signature learns nothing from the difference
    between a missing header and a wrong digest."""
    missing = api.post("/api/webhooks/razorpay", content=b"{}").json()
    wrong = post(api, event(), signature="0" * 64).json()

    assert missing == wrong


def test_the_route_binds_no_pydantic_body_model():
    """FastAPI's body binding consumes and re-encodes the request, and a
    signature over re-encoded bytes proves nothing (P§24).

    Easy to undo by accident - adding a typed body parameter looks like an
    improvement - so the absence is asserted rather than trusted.
    """
    import inspect

    from pydantic import BaseModel

    from app.api.routes.webhooks import razorpay_webhook

    for parameter in inspect.signature(razorpay_webhook).parameters.values():
        annotation = parameter.annotation
        assert not (isinstance(annotation, type) and issubclass(annotation, BaseModel))


def test_the_comparison_is_constant_time():
    """A byte-by-byte comparison that returns early leaks the signature."""
    import inspect

    from app.services import webhook_service

    source = inspect.getsource(webhook_service.verify_signature)

    assert "compare_digest" in source
    assert "==" not in source.split("expected =")[1]


# --------------------------------------------------------------------------
# Deduplication — M12's exit condition, half two
# --------------------------------------------------------------------------


def test_a_duplicate_event_causes_one_transition(session, api, paid_order):
    """P§25, P§26. The second delivery is answered 200 and changes nothing."""
    first = post(api, event(event_id="evt_dup"))
    second = post(api, event(event_id="evt_dup"))

    assert first.json()["status"] == "processed"
    assert second.status_code == 200
    assert second.json()["status"] == "ignored"

    payments = session.execute(
        text("SELECT count(*) FROM payments WHERE order_id = :o"), {"o": paid_order.id}
    ).scalar_one()
    assert payments == 1


def test_deduplication_is_enforced_by_the_database(session, api, paid_order):
    """Not by a "have I seen this?" query: two simultaneous deliveries would
    both pass a read-then-write check."""
    from sqlalchemy.exc import IntegrityError

    post(api, event(event_id="evt_constraint"))

    with pytest.raises(IntegrityError):
        session.execute(
            text(
                "INSERT INTO webhook_events (provider, event_id, event_type, signature,"
                " raw_body, payload, status) VALUES ('razorpay', 'evt_constraint', 'x',"
                " 's', '{}', '{}'::jsonb, 'RECEIVED')"
            )
        )
        session.flush()


# --------------------------------------------------------------------------
# Order-independent handling (P§27)
# --------------------------------------------------------------------------


def test_a_capture_confirms_the_order(session, api, paid_order):
    post(api, event("payment.captured"))

    session.expire(paid_order)
    assert paid_order.status == OrderStatus.PAYMENT_CONFIRMED.value


def test_a_failure_marks_the_order_failed(session, api, paid_order):
    post(api, event("payment.failed", error_description="card declined"))

    session.expire(paid_order)
    assert paid_order.status == OrderStatus.PAYMENT_FAILED.value


def test_a_late_failure_never_unconfirms_a_paid_order(session, api, paid_order):
    """Money that arrived does not un-arrive because an earlier attempt's
    failure was delivered slowly. Transitions never move backwards out of
    PAYMENT_CONFIRMED."""
    post(api, event("payment.captured", event_id="evt_cap", payment_id="pay_ok"))

    post(api, event("payment.failed", event_id="evt_fail", payment_id="pay_bad"))

    session.expire(paid_order)
    assert paid_order.status == OrderStatus.PAYMENT_CONFIRMED.value


def test_order_paid_confirms_and_is_idempotent(session, api, paid_order):
    post(api, event("order.paid", event_id="evt_paid_1"))
    post(api, event("order.paid", event_id="evt_paid_2"))

    session.expire(paid_order)
    assert paid_order.status == OrderStatus.PAYMENT_CONFIRMED.value


def test_applying_the_same_capture_twice_converges(session, api, paid_order):
    """Handlers assert a state rather than advance one, so re-applying is safe
    even when the event id differs."""
    post(api, event(event_id="evt_a", payment_id="pay_same"))
    post(api, event(event_id="evt_b", payment_id="pay_same"))

    count = session.execute(
        text("SELECT count(*) FROM payments WHERE razorpay_payment_id = 'pay_same'")
    ).scalar_one()
    assert count == 1
    session.expire(paid_order)
    assert paid_order.status == OrderStatus.PAYMENT_CONFIRMED.value


# --------------------------------------------------------------------------
# Events this system cannot act on
# --------------------------------------------------------------------------


def test_an_event_for_an_unknown_order_is_recorded_not_dropped(session, api):
    """P§27: it may have arrived before the order was committed, or belong to
    another system sharing the account. The stored row is what a reconciliation
    reads."""
    response = post(api, event(razorpay_order_id="order_NeverSeen", event_id="evt_orphan"))

    assert response.status_code == 200
    stored = session.execute(
        text("SELECT status, order_id FROM webhook_events WHERE event_id = 'evt_orphan'")
    ).one()
    assert stored.status == "RECEIVED"
    assert stored.order_id is None


def test_an_unsubscribed_event_is_recorded_and_ignored(session, api, paid_order):
    """Silently discarding it would make a future subscription change invisible."""
    response = post(api, event("refund.created", event_id="evt_refund"))

    assert response.status_code == 200
    assert response.json()["status"] == "ignored"
    status_value = session.execute(
        text("SELECT status FROM webhook_events WHERE event_id = 'evt_refund'")
    ).scalar_one()
    assert status_value == "IGNORED"


def test_an_unsubscribed_event_changes_no_order_state(session, api, paid_order):
    before = paid_order.status

    post(api, event("refund.created", event_id="evt_refund_2"))

    session.expire(paid_order)
    assert paid_order.status == before


# --------------------------------------------------------------------------
# What is stored
# --------------------------------------------------------------------------


def test_the_raw_body_is_stored_exactly_as_received(session, api, paid_order):
    """P§24. What was verified is what is kept, so a later audit can re-verify."""
    body = event(event_id="evt_raw")
    raw, _ = signed(body)

    post(api, body)

    stored = session.execute(
        text("SELECT raw_body FROM webhook_events WHERE event_id = 'evt_raw'")
    ).scalar_one()
    assert stored.encode("utf-8") == raw


def test_the_payment_row_records_what_the_provider_said(session, api, paid_order):
    post(api, event(amount=99900, payment_id="pay_detail"))

    row = session.execute(
        text(
            "SELECT status, amount, amount_minor, currency, method FROM payments"
            " WHERE razorpay_payment_id = 'pay_detail'"
        )
    ).one()
    assert row.status == "CAPTURED"
    assert row.amount == Decimal("999.00")
    assert row.amount_minor == 99900
    assert row.method == "upi"


def test_a_failure_reason_is_stored_but_never_returned(session, api, paid_order):
    """F§25: internal only, never rendered raw to a buyer."""
    response = post(api, event("payment.failed", error_description="issuer declined the card"))

    assert "issuer declined" not in response.text
    stored = session.execute(
        text("SELECT failure_reason FROM payments WHERE order_id = :o"), {"o": paid_order.id}
    ).scalar_one()
    assert stored == "issuer declined the card"


def test_no_payment_row_is_written_by_anything_but_a_webhook(session, api, paid_order):
    """ADR-012. Not by checkout, not by a buyer saying they paid, not by a
    frontend callback - asserted by there being no row until an event arrives."""
    before = session.execute(
        text("SELECT count(*) FROM payments WHERE order_id = :o"), {"o": paid_order.id}
    ).scalar_one()

    post(api, event())

    after = session.execute(
        text("SELECT count(*) FROM payments WHERE order_id = :o"), {"o": paid_order.id}
    ).scalar_one()
    assert (before, after) == (0, 1)


def test_an_unknown_event_without_an_id_still_deduplicates(session, api, paid_order):
    """A delivery carrying no event id falls back to a digest of the body, so it
    cannot be processed repeatedly."""
    body = {
        "event": "payment.captured",
        "payload": {
            "payment": {
                "entity": {
                    "id": "pay_noid",
                    "order_id": "order_TestModeXYZ",
                    "amount": 99900,
                    "currency": "INR",
                }
            }
        },
    }

    first = post(api, body)
    second = post(api, body)

    assert first.json()["status"] == "processed"
    assert second.json()["status"] == "ignored"
