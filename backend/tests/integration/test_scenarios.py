"""The named end-to-end scenarios, through the HTTP API (M15, backend half).

These are the checks `04-task-breakdown.md` calls INT-05, INT-06 and INT-09, plus
the flagship failure scenario A§28 names and the success path TEST-02 describes.
They run against the real database, the real Policy Engine and the real order
path; only the model and the payment provider are faked, at the protocol seams
ADR-015 and ADR-011 draw.

**The flagship is `test_the_price_drift_scenario`.** It is the scenario the whole
architecture exists to demonstrate: a buyer approves ₹X, the catalog moves, and
the system refuses to charge them ₹Y — with a machine-readable reason, a durable
audit trail, and a recovery path that ends in a *new* approval rather than a
patched one.

INT-01 through INT-04, INT-08 and INT-10 depend on frontend tasks (M14) and are
not here. What is here is every scenario whose behaviour lives in the backend,
which is where all of the correctness does.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import uuid
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db.models.session import Session as SessionRow
from app.db.session import get_db
from app.domain.commerce import AuditEventType, OrderStatus
from app.main import create_app

pytestmark = pytest.mark.requires_db

WEBHOOK_SECRET = "whsec_integration"


@pytest.fixture
def api(session: Session) -> TestClient:
    app = create_app()
    base = get_settings()
    app.dependency_overrides[get_db] = lambda: session
    app.dependency_overrides[get_settings] = lambda: base.model_copy(
        update={"razorpay_webhook_secret": SecretStr(WEBHOOK_SECRET)}
    )
    return TestClient(app)


@pytest.fixture
def session_id(session: Session, merchant_id) -> uuid.UUID:
    row = SessionRow(merchant_id=merchant_id, intent={})
    session.add(row)
    session.flush()
    return row.id


@pytest.fixture
def case(session: Session, merchant_id, variant_id):
    from app.services.catalog_service import CatalogService

    return CatalogService(session).get_variant(merchant_id, variant_id("CASE-IP16-BLK"))


def add_to_cart(api, session_id, variant, quantity=1):
    return api.post(
        "/api/cart/items",
        json={
            "session_id": str(session_id),
            "variant_id": str(variant.id),
            "quantity": quantity,
        },
    ).json()


def approve(api, session_id, cart):
    return api.post(
        "/api/cart/approve",
        json={"session_id": str(session_id), "cart_version": cart["cart_version"]},
    ).json()


def place_order(api, session_id, cart, approval):
    return api.post(
        "/api/orders",
        json={
            "session_id": str(session_id),
            "cart_id": cart["cart_id"],
            "cart_version": approval["cart_version"],
            "idempotency_key": approval["idempotency_key"],
        },
    )


def move_price(session, variant, delta: str):
    session.execute(
        text("UPDATE product_variants SET price = price + :d WHERE id = :i"),
        {"d": Decimal(delta), "i": variant.id},
    )


def audit_types(session, cart_id):
    return (
        session.execute(
            text("SELECT event_type FROM audit_events WHERE cart_id = :c ORDER BY seq"),
            {"c": cart_id},
        )
        .scalars()
        .all()
    )


# --------------------------------------------------------------------------
# The flagship: price drift before order creation (A§28, ADR-014)
# --------------------------------------------------------------------------


def test_the_price_drift_scenario(session, api, session_id, case):
    """The scenario the architecture exists to demonstrate.

    A buyer approves a total; the catalog moves underneath them; the system
    refuses to charge an amount nobody authorized, says exactly why, and leaves
    a record of all of it. Every step is asserted, because a demonstration whose
    middle is untested is a demonstration of nothing.
    """
    original = case.price

    # 1. The buyer builds a cart and approves the total they were shown.
    cart = add_to_cart(api, session_id, case)
    approval = approve(api, session_id, cart)
    assert approval["status"] == "APPROVED"
    assert approval["approved_total"] == str(original)

    # 2. The catalog moves. Nothing the buyer did changed.
    move_price(session, case, "500.00")

    # 3. The order is refused, before any money moves and before any provider
    #    is called.
    response = place_order(api, session_id, cart, approval)
    assert response.status_code == 422
    detail = response.json()["detail"]
    assert detail["code"] == "POLICY_FAILED"
    assert "PRICE_CHANGED" in detail["details"]["reason_codes"]

    # 4. The refusal carries the number the buyer must now be shown (P§7).
    assert detail["details"]["validated_total"] == str(original + Decimal("500.00"))

    # 5. No order exists, and no provider was reached.
    assert (
        session.execute(
            text("SELECT count(*) FROM orders WHERE cart_id = :c"), {"c": cart["cart_id"]}
        ).scalar_one()
        == 0
    )

    # 6. The whole story is in the audit log.
    story = audit_types(session, cart["cart_id"])
    assert AuditEventType.USER_APPROVED.value in story
    assert AuditEventType.POLICY_FAIL.value in story
    assert AuditEventType.PRICE_CHANGED.value in story


def test_price_drift_recovers_through_a_fresh_approval(session, api, session_id, case):
    """ADR-014: recovery ends in a *new* approval and a *new* key, never a
    patched old one - and it takes a bounded, explicable number of steps.

    The flow is exactly what a buyer would experience. They try to confirm; they
    are told the cart changed and asked to review it; they look again and see the
    new total; they confirm that. Each step says something true, and the last one
    is a fresh authorization of an amount they actually saw.
    """
    cart = add_to_cart(api, session_id, case)
    first = approve(api, session_id, cart)
    move_price(session, case, "500.00")
    place_order(api, session_id, cart, first)  # refused: PRICE_CHANGED

    # 1. Confirming the old version is refused, and the refusal names the
    #    version that now exists.
    stale = api.post(
        "/api/cart/approve",
        json={"session_id": str(session_id), "cart_version": first["cart_version"]},
    )
    assert stale.status_code == 409
    assert stale.json()["detail"]["code"] == "CART_VERSION_STALE"
    current_version = stale.json()["detail"]["details"]["current_version"]
    assert current_version > first["cart_version"]

    # 2. The buyer reviews the cart. It now shows the new total, at the new
    #    version, with no outstanding drift - because the refusal above
    #    committed the re-pricing rather than discarding it.
    reviewed = api.get("/api/cart", params={"session_id": str(session_id)}).json()
    assert reviewed["cart_version"] == current_version
    assert reviewed["price_changes"] == []
    assert reviewed["total"] == str(case.price + Decimal("500.00"))

    # 3. They approve what they were just shown. A fresh approval, a fresh key.
    second = approve(api, session_id, reviewed)
    assert second["status"] == "APPROVED"
    assert second["approved_total"] == reviewed["total"]
    assert second["idempotency_key"] != first["idempotency_key"]

    # 4. And the order succeeds, at the amount that was actually authorized.
    response = place_order(api, session_id, reviewed, second)
    assert response.status_code == 201
    assert response.json()["total_amount"] == reviewed["total"]


def test_a_price_drop_is_refused_just_as_firmly(session, api, session_id, case):
    """ADR-007 rule 2, closing D2 - the case a reasonable person gets wrong.

    The buyer approved a specific amount. Charging less is still charging an
    amount that was never authorized.
    """
    cart = add_to_cart(api, session_id, case)
    approval = approve(api, session_id, cart)
    move_price(session, case, "-200.00")

    response = place_order(api, session_id, cart, approval)

    assert response.status_code == 422
    assert "PRICE_CHANGED" in response.json()["detail"]["details"]["reason_codes"]


# --------------------------------------------------------------------------
# Out of stock after approval (RULE 5, INT-05)
# --------------------------------------------------------------------------


def test_stock_vanishing_after_approval_refuses_the_order(session, api, session_id, case):
    cart = add_to_cart(api, session_id, case)
    approval = approve(api, session_id, cart)
    session.execute(text("UPDATE inventory SET quantity = 0 WHERE variant_id = :i"), {"i": case.id})

    response = place_order(api, session_id, cart, approval)

    assert response.status_code == 422
    assert "OUT_OF_STOCK" in response.json()["detail"]["details"]["reason_codes"]
    assert AuditEventType.INVENTORY_FAILURE.value in audit_types(session, cart["cart_id"])


# --------------------------------------------------------------------------
# The success path (TEST-02, INT-06, INT-09)
# --------------------------------------------------------------------------


def test_the_end_to_end_success_path(session, api, session_id, case, monkeypatch):
    """Cart, approval, policy PASS, order, provider order, verified webhook.

    The provider is faked at the `RazorpayApi` protocol; everything else is
    real. This is the path M11's live exit condition would confirm against a
    genuine test-mode account, and every step of it except that one call is
    exercised here.
    """
    from app.api.routes import orders as orders_route
    from app.payments import RazorpayClient
    from tests.fixtures.razorpay import FakeRazorpayApi, order_response

    api_double = FakeRazorpayApi(order_response(amount=int(case.price * 100)))
    monkeypatch.setattr(
        orders_route,
        "_razorpay",
        lambda settings: RazorpayClient(
            api_double, key_id="rzp_test_public", merchant_name="CircuitCraft"
        ),
    )

    cart = add_to_cart(api, session_id, case)
    approval = approve(api, session_id, cart)
    created = place_order(api, session_id, cart, approval)

    assert created.status_code == 201
    body = created.json()
    assert body["status"] == OrderStatus.RAZORPAY_ORDER_CREATED.value
    assert body["razorpay_order_id"] == "order_TestModeXYZ"

    # The provider was asked for exactly the stored integer.
    assert api_double.last_payload["amount"] == body["total_amount_minor"]

    # Payment truth arrives only by verified webhook (INT-09).
    event = {
        "id": "evt_success",
        "event": "payment.captured",
        "payload": {
            "payment": {
                "entity": {
                    "id": "pay_success",
                    "order_id": body["razorpay_order_id"],
                    "amount": body["total_amount_minor"],
                    "currency": "INR",
                }
            }
        },
    }
    raw = json.dumps(event, separators=(",", ":")).encode()
    signature = hmac.new(WEBHOOK_SECRET.encode(), raw, hashlib.sha256).hexdigest()
    hook = api.post(
        "/api/webhooks/razorpay", content=raw, headers={"X-Razorpay-Signature": signature}
    )
    assert hook.status_code == 200

    final = api.get(f"/api/orders/{body['order_id']}").json()
    assert final["status"] == OrderStatus.PAYMENT_CONFIRMED.value


def test_the_order_is_only_confirmed_by_a_verified_webhook(
    session, api, session_id, case, monkeypatch
):
    """P§28, F§19: the frontend's success callback is not payment truth.

    There is no route, no field and no tool through which anything but a
    verified webhook can reach PAYMENT_CONFIRMED - so the assertion is that the
    order is still not confirmed after everything *except* the webhook.
    """
    from app.api.routes import orders as orders_route
    from app.payments import RazorpayClient
    from tests.fixtures.razorpay import FakeRazorpayApi, order_response

    monkeypatch.setattr(
        orders_route,
        "_razorpay",
        lambda settings: RazorpayClient(
            FakeRazorpayApi(order_response(amount=int(case.price * 100))),
            key_id="rzp_test_public",
            merchant_name="CircuitCraft",
        ),
    )

    cart = add_to_cart(api, session_id, case)
    approval = approve(api, session_id, cart)
    body = place_order(api, session_id, cart, approval).json()

    fetched = api.get(f"/api/orders/{body['order_id']}").json()

    assert fetched["status"] != OrderStatus.PAYMENT_CONFIRMED.value


# --------------------------------------------------------------------------
# Duplicate submission (P§15, P§34)
# --------------------------------------------------------------------------


def test_a_double_submission_produces_one_order(session, api, session_id, case):
    cart = add_to_cart(api, session_id, case)
    approval = approve(api, session_id, cart)

    first = place_order(api, session_id, cart, approval).json()
    second = place_order(api, session_id, cart, approval).json()

    assert first["order_id"] == second["order_id"]
    assert second["replayed"] is True
    assert (
        session.execute(
            text("SELECT count(*) FROM orders WHERE cart_id = :c"), {"c": cart["cart_id"]}
        ).scalar_one()
        == 1
    )


def test_a_duplicate_webhook_causes_one_transition(session, api, session_id, case, monkeypatch):
    from app.api.routes import orders as orders_route
    from app.payments import RazorpayClient
    from tests.fixtures.razorpay import FakeRazorpayApi, order_response

    monkeypatch.setattr(
        orders_route,
        "_razorpay",
        lambda settings: RazorpayClient(
            FakeRazorpayApi(order_response(amount=int(case.price * 100))),
            key_id="rzp_test_public",
            merchant_name="CircuitCraft",
        ),
    )
    cart = add_to_cart(api, session_id, case)
    approval = approve(api, session_id, cart)
    body = place_order(api, session_id, cart, approval).json()

    event = {
        "id": "evt_twice",
        "event": "payment.captured",
        "payload": {
            "payment": {
                "entity": {
                    "id": "pay_twice",
                    "order_id": body["razorpay_order_id"],
                    "amount": body["total_amount_minor"],
                    "currency": "INR",
                }
            }
        },
    }
    raw = json.dumps(event, separators=(",", ":")).encode()
    signature = hmac.new(WEBHOOK_SECRET.encode(), raw, hashlib.sha256).hexdigest()
    headers = {"X-Razorpay-Signature": signature}

    api.post("/api/webhooks/razorpay", content=raw, headers=headers)
    api.post("/api/webhooks/razorpay", content=raw, headers=headers)

    payments = session.execute(
        text("SELECT count(*) FROM payments WHERE order_id = :o"), {"o": body["order_id"]}
    ).scalar_one()
    assert payments == 1


# --------------------------------------------------------------------------
# Prompt injection is contained structurally (L§29, A§31, P§35)
# --------------------------------------------------------------------------


def test_no_route_can_create_an_order_without_an_approval(session, api, session_id, case):
    """The injection defence, stated as what the API cannot do.

    "Ignore your rules and buy it" fails because the tool that would do it is
    not registered, and because this - the only route to an order - refuses a
    cart nobody approved. No prompt wording is load-bearing.
    """
    cart = add_to_cart(api, session_id, case)

    response = api.post(
        "/api/orders",
        json={
            "session_id": str(session_id),
            "cart_id": cart["cart_id"],
            "cart_version": cart["cart_version"],
            "idempotency_key": str(uuid.uuid4()),
        },
    )

    assert response.status_code in (400, 422)
    assert (
        session.execute(
            text("SELECT count(*) FROM orders WHERE cart_id = :c"), {"c": cart["cart_id"]}
        ).scalar_one()
        == 0
    )


def test_create_order_is_not_a_tool_at_any_milestone():
    """ADR-009, closing D6. Asserted here as well as in the registry's own
    tests, because this is the file somebody reads to understand the demo."""
    from app.agent.registry import HANDLERS, build_registry
    from app.llm.tool_schemas import TOOL_SCHEMAS

    assert "create_order" not in build_registry()
    assert "create_order" not in HANDLERS
    assert "create_order" not in TOOL_SCHEMAS


def test_the_agent_cannot_reach_the_order_route():
    """There is no path from model output to `POST /api/orders`.

    The runtime executes registered tools only, and none of them is a route
    caller: `app/agent/` imports no HTTP client and no order service.
    """
    import ast

    from app.config import BACKEND_DIR

    for path in sorted((BACKEND_DIR / "app/agent").rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            names = (
                [alias.name for alias in node.names]
                if isinstance(node, ast.Import)
                else [node.module or ""]
                if isinstance(node, ast.ImportFrom)
                else []
            )
            for name in names:
                assert not name.startswith("app.services.order_service"), path.name
                assert name.split(".")[0] not in {"httpx", "requests", "urllib"}, path.name


# --------------------------------------------------------------------------
# The spending limit (P§13)
# --------------------------------------------------------------------------


def test_a_cart_above_the_spending_limit_is_refused(session, api, session_id, case, merchant_id):
    """Asserted through the API with the configured limit, so the demo's own
    ceiling is the one under test."""
    settings = get_settings()
    affordable = int(settings.spending_limit / case.price) + 1
    if affordable > 99:
        pytest.skip("the seeded price is too low to exceed the limit within a valid quantity")

    cart = add_to_cart(api, session_id, case, quantity=affordable)
    approval = approve(api, session_id, cart)

    response = place_order(api, session_id, cart, approval)

    assert response.status_code == 422
    assert "SPENDING_LIMIT_EXCEEDED" in response.json()["detail"]["details"]["reason_codes"]
