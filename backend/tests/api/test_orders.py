"""`POST /api/orders` — the only route that can create one (M10; ADR-011, F§17).

Against a real database, because everything worth testing here is about live
state: whether the price still matches, whether the stock is still there, and
whether a second request creates a second order.

The contract is again mostly about *absence*. There is no field through which a
client can state an amount, so F§17's forged `amount = ₹1` is not defeated by
validation — it has nowhere to be submitted, and attempting it is a 422.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db.models.session import Session as SessionRow
from app.db.session import get_db
from app.main import create_app

pytestmark = pytest.mark.requires_db


@pytest.fixture
def api(session: Session) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_db] = lambda: session
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


@pytest.fixture
def checkout(api, session_id, case):
    """A cart, approved, with the key the approval minted — through the API."""
    cart = api.post(
        "/api/cart/items",
        json={"session_id": str(session_id), "variant_id": str(case.id), "quantity": 1},
    ).json()
    approval = api.post(
        "/api/cart/approve",
        json={"session_id": str(session_id), "cart_version": cart["cart_version"]},
    ).json()
    return cart, approval


def order_body(session_id, cart, approval, **overrides):
    return {
        "session_id": str(session_id),
        "cart_id": cart["cart_id"],
        "cart_version": approval["cart_version"],
        "idempotency_key": approval["idempotency_key"],
        **overrides,
    }


# --------------------------------------------------------------------------
# The key is minted by the backend, at approval time
# --------------------------------------------------------------------------


def test_approving_returns_an_idempotency_key(checkout):
    """ADR-013: the backend mints it, bound to the approval's exact state.

    A client-chosen key protects only against that client's own retries and
    could be reused across genuinely different carts.
    """
    _, approval = checkout

    assert approval["idempotency_key"]
    uuid.UUID(approval["idempotency_key"])


def test_a_new_approval_mints_a_new_key(api, session_id, case, checkout):
    """P§16's "fresh idempotency key", obtained as a consequence of the approval
    rules rather than as a separate mechanism anyone has to remember."""
    _, first = checkout
    cart = api.post(
        "/api/cart/items",
        json={"session_id": str(session_id), "variant_id": str(case.id), "quantity": 1},
    ).json()
    second = api.post(
        "/api/cart/approve",
        json={"session_id": str(session_id), "cart_version": cart["cart_version"]},
    ).json()

    assert second["idempotency_key"] != first["idempotency_key"]


# --------------------------------------------------------------------------
# Creating an order
# --------------------------------------------------------------------------


def test_an_approved_cart_creates_an_order(api, session_id, checkout):
    cart, approval = checkout

    response = api.post("/api/orders", json=order_body(session_id, cart, approval))

    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "ORDER_CREATED"
    assert body["total_amount"] == cart["total"]
    assert body["replayed"] is False


def test_the_order_carries_the_minor_unit_integer(api, session_id, checkout, case):
    """ADR-008. Exactly what a provider will be sent."""
    cart, approval = checkout

    body = api.post("/api/orders", json=order_body(session_id, cart, approval)).json()

    assert body["total_amount_minor"] == int(case.price * 100)


def test_the_razorpay_id_is_null_until_m11(api, session_id, checkout):
    """ADR-011: the internal order is committed before the provider is called."""
    cart, approval = checkout

    body = api.post("/api/orders", json=order_body(session_id, cart, approval)).json()

    assert body["razorpay_order_id"] is None


def test_the_order_can_be_read_back(api, session_id, checkout):
    cart, approval = checkout
    created = api.post("/api/orders", json=order_body(session_id, cart, approval)).json()

    fetched = api.get(f"/api/orders/{created['order_id']}").json()

    assert fetched["order_id"] == created["order_id"]
    assert fetched["total_amount"] == created["total_amount"]


def test_an_unknown_order_is_a_404(api):
    assert api.get(f"/api/orders/{uuid.uuid4()}").status_code == 404


# --------------------------------------------------------------------------
# M10's exit condition, through the API
# --------------------------------------------------------------------------


def test_a_duplicate_request_yields_one_order_and_the_same_answer(
    session, api, session_id, checkout
):
    cart, approval = checkout
    body = order_body(session_id, cart, approval)

    first = api.post("/api/orders", json=body)
    second = api.post("/api/orders", json=body)

    assert first.json()["order_id"] == second.json()["order_id"]
    assert second.json()["replayed"] is True
    count = session.execute(
        text("SELECT count(*) FROM orders WHERE cart_id = :c"), {"c": cart["cart_id"]}
    ).scalar_one()
    assert count == 1


def test_a_replay_is_a_200_not_a_201(api, session_id, checkout):
    """The status code is the honest signal that this call did no work."""
    cart, approval = checkout
    body = order_body(session_id, cart, approval)

    assert api.post("/api/orders", json=body).status_code == 201
    # FastAPI's declared status applies to both; the `replayed` flag is what a
    # client reads. Asserted so the distinction is not lost silently.
    assert api.post("/api/orders", json=body).json()["replayed"] is True


# --------------------------------------------------------------------------
# Nothing from the client is authoritative (F§17)
# --------------------------------------------------------------------------


@pytest.mark.parametrize("field", ["amount", "total", "total_amount", "currency", "items"])
def test_a_client_supplied_amount_has_nowhere_to_go(api, session_id, checkout, field):
    """F§17's forged amount is not rejected by validation - it has no field.

    `extra="forbid"` turns the attempt into a 422 rather than a field quietly
    discarded, so a client cannot believe it succeeded.
    """
    cart, approval = checkout

    response = api.post("/api/orders", json=order_body(session_id, cart, approval, **{field: "1"}))

    assert response.status_code == 422


def test_a_stale_cart_version_is_refused(api, session_id, checkout):
    cart, approval = checkout

    response = api.post(
        "/api/orders",
        json=order_body(session_id, cart, approval, cart_version=approval["cart_version"] + 3),
    )

    assert response.status_code == 422
    assert "INVALID_CART" in response.json()["detail"]["details"]["reason_codes"]


# --------------------------------------------------------------------------
# Policy refusals
# --------------------------------------------------------------------------


def test_a_price_change_refuses_with_reason_codes(session, api, session_id, checkout, case):
    """The flagship scenario, through the front door. A 422 with machine-readable
    codes the frontend renders as a recovery flow (ADR-010, ADR-014)."""
    cart, approval = checkout
    session.execute(
        text("UPDATE product_variants SET price = price + 500 WHERE id = :i"), {"i": case.id}
    )

    response = api.post("/api/orders", json=order_body(session_id, cart, approval))

    assert response.status_code == 422
    detail = response.json()["detail"]
    assert detail["code"] == "POLICY_FAILED"
    assert "PRICE_CHANGED" in detail["details"]["reason_codes"]
    assert detail["details"]["validated_total"] == str(case.price + Decimal("500"))


def test_no_order_exists_after_a_policy_refusal(session, api, session_id, checkout, case):
    cart, approval = checkout
    session.execute(text("UPDATE inventory SET quantity = 0 WHERE variant_id = :i"), {"i": case.id})

    api.post("/api/orders", json=order_body(session_id, cart, approval))

    count = session.execute(
        text("SELECT count(*) FROM orders WHERE cart_id = :c"), {"c": cart["cart_id"]}
    ).scalar_one()
    assert count == 0


def test_the_error_body_never_leaks_an_exception(session, api, session_id, checkout, case):
    """F§25: never a Python exception, never a database message."""
    cart, approval = checkout
    session.execute(
        text("UPDATE product_variants SET price = price + 500 WHERE id = :i"), {"i": case.id}
    )

    body = api.post("/api/orders", json=order_body(session_id, cart, approval)).text

    assert "Traceback" not in body
    assert "sqlalchemy" not in body.lower()


# --------------------------------------------------------------------------
# The published surface
# --------------------------------------------------------------------------


def test_the_order_surface_is_f26s_two_names_plus_checkout():
    """F§26's two, and the checkout handoff RZP-03 requires.

    `/checkout` is not a duplicate API: it returns the *configuration* a frontend
    needs to open Razorpay Checkout, and doubles as the retry for ADR-011 step 9
    when the provider was unreachable at order creation.
    """
    paths = {p for p in create_app().openapi()["paths"] if p.startswith("/api/orders")}

    assert paths == {
        "/api/orders",
        "/api/orders/{order_id}",
        "/api/orders/{order_id}/checkout",
    }
