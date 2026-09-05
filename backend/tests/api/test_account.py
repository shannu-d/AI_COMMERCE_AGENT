"""`/api/account/orders` — a customer's own purchase history (ADR-023 §2).

The property worth proving is not that a list endpoint paginates. It is that
**ownership is derived from the session join and cannot be asserted by a
request**: the same order is present for the buyer, absent for a stranger, and
unreachable by id for anyone else — with no `user_id` column on `orders` for the
three answers to disagree about.

The order here is a real one, created through `/api/cart/approve` and
`/api/orders`, because an order fabricated by inserting a row would not prove
that the money path and the ownership path agree.
"""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.main import create_app

pytestmark = pytest.mark.requires_db


@pytest.fixture
def api(session: Session) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_db] = lambda: session
    return TestClient(app)


@pytest.fixture
def placed_order(api: TestClient, customer_headers: dict[str, str], variant_id) -> dict:
    """One paid-for-real-shaped order, placed by the `customer_headers` shopper."""
    session_id = api.post("/api/sessions", headers=customer_headers).json()["session_id"]
    cart = api.post(
        "/api/cart/items",
        json={
            "session_id": session_id,
            "variant_id": str(variant_id("CASE-IP16-BLK")),
            "quantity": 1,
        },
        headers=customer_headers,
    ).json()
    approval = api.post(
        "/api/cart/approve",
        json={"session_id": session_id, "cart_version": cart["cart_version"]},
        headers=customer_headers,
    ).json()
    created = api.post(
        "/api/orders",
        json={
            "session_id": session_id,
            "cart_id": cart["cart_id"],
            "cart_version": approval["cart_version"],
            "idempotency_key": approval["idempotency_key"],
        },
        headers=customer_headers,
    )
    assert created.status_code == 201, created.text
    return {"session_id": session_id, "order": created.json()}


def test_an_order_placed_on_a_session_that_was_anonymous_still_reaches_the_account(
    api: TestClient, customer_headers: dict[str, str], variant_id
) -> None:
    """Signing in *before* shopping must work as well as signing in after.

    Ownership is derived from `orders.session_id -> sessions.user_id` and is
    never written onto the order, so a session still anonymous when the order is
    created produces an order belonging to nobody — and permanently, because the
    buyer has already signed in and their next login has nothing left to claim.
    The buyer who opened a second tab, or who signed in and then started
    browsing, would simply never see what they bought.

    `POST /api/orders` therefore claims the session for a signed-in customer, on
    the same terms as login: an anonymous session only, never one already owned
    by somebody else, and never for a merchant administrator.
    """
    session_id = api.post("/api/sessions").json()["session_id"]  # nobody's yet
    cart = api.post(
        "/api/cart/items",
        json={
            "session_id": session_id,
            "variant_id": str(variant_id("CASE-IP16-BLK")),
            "quantity": 1,
        },
        headers=customer_headers,
    ).json()
    approval = api.post(
        "/api/cart/approve",
        json={"session_id": session_id, "cart_version": cart["cart_version"]},
        headers=customer_headers,
    ).json()
    created = api.post(
        "/api/orders",
        json={
            "session_id": session_id,
            "cart_id": cart["cart_id"],
            "cart_version": approval["cart_version"],
            "idempotency_key": approval["idempotency_key"],
        },
        headers=customer_headers,
    )
    assert created.status_code == 201, created.text

    mine = api.get("/api/account/orders", headers=customer_headers).json()

    assert created.json()["order_id"] in [row["order_id"] for row in mine["items"]]


def test_the_buyer_sees_their_own_order(
    api: TestClient, customer_headers: dict[str, str], placed_order: dict
) -> None:
    body = api.get("/api/account/orders", headers=customer_headers).json()
    assert body["total"] == 1
    assert body["items"][0]["order_id"] == placed_order["order"]["order_id"]
    # Money is a string on the way out, here as everywhere (ADR-008).
    assert isinstance(body["items"][0]["total_amount"], str)


def test_another_customer_sees_none_of_it(
    api: TestClient, other_customer_headers: dict[str, str], placed_order: dict
) -> None:
    body = api.get("/api/account/orders", headers=other_customer_headers).json()
    assert body["total"] == 0
    assert body["items"] == []


def test_another_customer_cannot_read_the_order_by_id(
    api: TestClient, other_customer_headers: dict[str, str], placed_order: dict
) -> None:
    """404, the same answer as an id that does not exist — knowing an order id
    must not be enough to read it, and the refusal must not confirm it is real."""
    order_id = placed_order["order"]["order_id"]
    mine = api.get(f"/api/orders/{order_id}", headers=other_customer_headers)
    invented = api.get(f"/api/orders/{uuid.uuid4()}", headers=other_customer_headers)
    assert mine.status_code == invented.status_code == 404


def test_an_anonymous_caller_cannot_read_the_order_by_id(
    api: TestClient, placed_order: dict
) -> None:
    order_id = placed_order["order"]["order_id"]
    assert api.get(f"/api/orders/{order_id}").status_code == 404


def test_the_owner_can_still_read_the_order_by_id(
    api: TestClient, customer_headers: dict[str, str], placed_order: dict
) -> None:
    order_id = placed_order["order"]["order_id"]
    assert api.get(f"/api/orders/{order_id}", headers=customer_headers).status_code == 200


def test_checkout_is_refused_to_a_stranger(
    api: TestClient, other_customer_headers: dict[str, str], placed_order: dict
) -> None:
    """The payment path is guarded by the same rule as the read path — a
    stranger must not be able to open a Razorpay checkout for someone's order."""
    order_id = placed_order["order"]["order_id"]
    assert (
        api.post(f"/api/orders/{order_id}/checkout", headers=other_customer_headers).status_code
        == 404
    )


def test_the_history_needs_a_customer(api: TestClient, merchant_headers: dict[str, str]) -> None:
    assert api.get("/api/account/orders").status_code == 401
    # A merchant administrator is 403, not an empty list: the dashboard is not
    # a shopping surface, and "you have no orders" would suggest it might be.
    assert api.get("/api/account/orders", headers=merchant_headers).status_code == 403


def test_an_order_placed_anonymously_appears_after_the_session_is_claimed(
    api: TestClient, variant_id
) -> None:
    """The reason claiming exists: a purchase made before signing up is still
    the buyer's, and it becomes visible without anything being copied."""
    from tests.api.conftest import PASSWORD, unique_email

    session_id = api.post("/api/sessions").json()["session_id"]
    cart = api.post(
        "/api/cart/items",
        json={
            "session_id": session_id,
            "variant_id": str(variant_id("CASE-IP16-BLK")),
            "quantity": 1,
        },
    ).json()
    approval = api.post(
        "/api/cart/approve",
        json={"session_id": session_id, "cart_version": cart["cart_version"]},
    ).json()
    created = api.post(
        "/api/orders",
        json={
            "session_id": session_id,
            "cart_id": cart["cart_id"],
            "cart_version": approval["cart_version"],
            "idempotency_key": approval["idempotency_key"],
        },
    )
    assert created.status_code == 201, created.text

    signed_up = api.post(
        "/api/auth/register",
        json={
            "email": unique_email("late"),
            "password": PASSWORD,
            "session_id": session_id,
        },
    ).json()
    assert signed_up["session_claimed"] is True

    headers = {"Authorization": f"Bearer {signed_up['access_token']}"}
    body = api.get("/api/account/orders", headers=headers).json()
    assert [row["order_id"] for row in body["items"]] == [created.json()["order_id"]]
