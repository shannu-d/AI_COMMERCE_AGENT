"""The cart endpoints (M7; F§12, F§26).

Against a real database, because what these routes are for is turning a request
into an authoritative total, and an authoritative total is one the catalog
produced.

The contract under test is mostly a contract about *absence*: there is no field
through which a client can state a price, and the routes are exactly the four
F§26 names with no "recalculate" or "set total" alongside them.
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
    """A client whose requests run in the test's own rolled-back transaction."""
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
    """A real, in-stock iPhone 16 case, read through the same service the route
    uses — so the price this test expects is the price the route will find."""
    from app.services.catalog_service import CatalogService

    return CatalogService(session).get_variant(merchant_id, variant_id("CASE-IP16-BLK"))


# --------------------------------------------------------------------------
# The total is the backend's
# --------------------------------------------------------------------------


def test_adding_an_item_returns_a_backend_computed_total(api, session_id, case):
    response = api.post(
        "/api/cart/items",
        json={"session_id": str(session_id), "variant_id": str(case.id), "quantity": 2},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == str((case.price * 2).quantize(Decimal("0.01")))
    assert body["items"][0]["unit_price"] == str(case.price.quantize(Decimal("0.01")))


def test_money_is_a_string_on_the_wire(api, session_id, case):
    """ADR-008. A `Decimal` field would still serialize as a JSON number."""
    response = api.post(
        "/api/cart/items",
        json={"session_id": str(session_id), "variant_id": str(case.id), "quantity": 1},
    )

    assert f'"total":"{case.price.quantize(Decimal("0.01"))}"' in response.text.replace(" ", "")


def test_a_client_supplied_price_is_refused(api, session_id, case):
    """F§12, A§13. Not ignored — refused, because an ignored field looks honoured."""
    response = api.post(
        "/api/cart/items",
        json={
            "session_id": str(session_id),
            "variant_id": str(case.id),
            "quantity": 1,
            "unit_price": "1.00",
        },
    )

    assert response.status_code == 422


def test_a_client_supplied_total_is_refused(api, session_id, case):
    response = api.post(
        "/api/cart/items",
        json={
            "session_id": str(session_id),
            "variant_id": str(case.id),
            "quantity": 1,
            "total": "1.00",
        },
    )

    assert response.status_code == 422


# --------------------------------------------------------------------------
# Versioning is visible to the client
# --------------------------------------------------------------------------


def test_every_mutation_moves_the_version(api, session_id, case):
    """F§13: the frontend does not decide this; the backend tracks it."""
    first = api.post(
        "/api/cart/items",
        json={"session_id": str(session_id), "variant_id": str(case.id), "quantity": 1},
    ).json()
    item_id = first["items"][0]["item_id"]

    second = api.patch(
        f"/api/cart/items/{item_id}",
        json={"session_id": str(session_id), "quantity": 3},
    ).json()
    third = api.request(
        "DELETE", f"/api/cart/items/{item_id}", params={"session_id": str(session_id)}
    ).json()

    assert second["cart_version"] == first["cart_version"] + 1
    assert third["cart_version"] == second["cart_version"] + 1


def test_the_version_is_on_every_response(api, session_id, case):
    body = api.post(
        "/api/cart/items",
        json={"session_id": str(session_id), "variant_id": str(case.id), "quantity": 1},
    ).json()

    assert "cart_version" in body
    assert isinstance(body["cart_version"], int)


# --------------------------------------------------------------------------
# What the routes refuse
# --------------------------------------------------------------------------


def test_an_unknown_session_is_a_404(api, case):
    """Same rule as `/api/chat`: rejected, never silently created."""
    response = api.post(
        "/api/cart/items",
        json={"session_id": str(uuid.uuid4()), "variant_id": str(case.id), "quantity": 1},
    )

    assert response.status_code == 404


def test_an_unknown_variant_is_a_404(api, session_id):
    response = api.post(
        "/api/cart/items",
        json={"session_id": str(session_id), "variant_id": str(uuid.uuid4()), "quantity": 1},
    )

    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "VARIANT_NOT_FOUND"


def test_an_out_of_stock_variant_is_a_409(api, session_id, merchant_id, variant_id):
    """A conflict with the world's current state, not a malformed request."""
    response = api.post(
        "/api/cart/items",
        json={
            "session_id": str(session_id),
            "variant_id": str(variant_id("CASE-IP16-CLR")),
            "quantity": 1,
        },
    )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "OUT_OF_STOCK"


def test_a_quantity_beyond_the_bound_is_a_422(api, session_id, case):
    response = api.post(
        "/api/cart/items",
        json={"session_id": str(session_id), "variant_id": str(case.id), "quantity": 500},
    )

    assert response.status_code == 422


def test_reading_a_cart_that_does_not_exist_is_a_404(api, session_id):
    """`GET /api/cart` on a fresh session says so; it does not mint one."""
    response = api.get("/api/cart", params={"session_id": str(session_id)})

    assert response.status_code == 404


# --------------------------------------------------------------------------
# The published surface
# --------------------------------------------------------------------------


def test_the_cart_surface_is_exactly_f26s_names():
    """F§26: do not create duplicate APIs where equivalent services exist.

    There is no "recalculate" route because every one of these recalculates, and
    no "set totals" route because nobody may set one. `POST /api/cart/approve`
    arrived with M8 and is the **only** path that writes an APPROVED row.
    """
    paths = set(create_app().openapi()["paths"])
    cart_paths = {p for p in paths if p.startswith("/api/cart")}

    assert cart_paths == {
        "/api/cart",
        "/api/cart/items",
        "/api/cart/items/{item_id}",
        "/api/cart/approve",
    }


def test_no_cart_response_field_carries_a_stock_quantity(api, session_id, case):
    """ADR-009, closing E5."""
    body = api.post(
        "/api/cart/items",
        json={"session_id": str(session_id), "variant_id": str(case.id), "quantity": 1},
    ).json()

    assert body["items"][0]["stock_status"] in {"IN_STOCK", "LOW_STOCK"}
    assert "quantity_available" not in body["items"][0]
    assert "available_quantity" not in str(body)


def test_a_price_change_is_reported_to_the_client(api, session, session_id, case):
    """ADR-014: the buyer is told, in their own terms, both directions."""
    api.post(
        "/api/cart/items",
        json={"session_id": str(session_id), "variant_id": str(case.id), "quantity": 1},
    )
    session.execute(
        text("UPDATE product_variants SET price = price + 300 WHERE id = :id"), {"id": case.id}
    )

    body = api.get("/api/cart", params={"session_id": str(session_id)}).json()

    assert body["price_changes"]
    assert body["price_changes"][0]["increased"] is True


# --------------------------------------------------------------------------
# POST /api/cart/approve — the only path that writes an APPROVED row (M8)
# --------------------------------------------------------------------------


def _add(api, session_id, case, quantity=1):
    return api.post(
        "/api/cart/items",
        json={"session_id": str(session_id), "variant_id": str(case.id), "quantity": quantity},
    ).json()


def test_approving_the_current_version_records_an_approval(api, session_id, case):
    cart = _add(api, session_id, case)

    response = api.post(
        "/api/cart/approve",
        json={"session_id": str(session_id), "cart_version": cart["cart_version"]},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "APPROVED"
    assert body["cart_version"] == cart["cart_version"]
    assert body["approved_at"] is not None


def test_approving_a_stale_version_is_a_409(api, session_id, case, merchant_id, variant_id):
    """M8's exit condition, at the edge. The buyer's screen said version N; they
    added something; the cart is N+1. A 409 rather than a 422 because the
    request was well-formed and the world moved."""
    first = _add(api, session_id, case)
    _add(api, session_id, case)  # the cart moves underneath them

    response = api.post(
        "/api/cart/approve",
        json={"session_id": str(session_id), "cart_version": first["cart_version"]},
    )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "CART_VERSION_STALE"


def test_a_stated_total_that_no_longer_matches_is_a_409(api, session_id, case):
    cart = _add(api, session_id, case)

    response = api.post(
        "/api/cart/approve",
        json={
            "session_id": str(session_id),
            "cart_version": cart["cart_version"],
            "expected_total": "1.00",
        },
    )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "TOTAL_CHANGED"


def test_a_price_change_before_approval_is_caught_at_the_edge(api, session, session_id, case):
    """A§28's scenario, entering through the front door.

    The route re-prices the cart *before* checking the version. A catalog change
    since the buyer's screen was drawn therefore bumps the version, and the
    version they submitted no longer matches - so they are asked to look again
    rather than authorizing a total that is no longer real.
    """
    cart = _add(api, session_id, case)
    session.execute(
        text("UPDATE product_variants SET price = price + 400 WHERE id = :i"), {"i": case.id}
    )

    response = api.post(
        "/api/cart/approve",
        json={"session_id": str(session_id), "cart_version": cart["cart_version"]},
    )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "CART_VERSION_STALE"


def test_the_approval_response_carries_the_cart_it_approved(api, session_id, case):
    """An approval is a claim about a specific cart state; returning one without
    that state would make it unverifiable by the client that just made it."""
    cart = _add(api, session_id, case)

    body = api.post(
        "/api/cart/approve",
        json={"session_id": str(session_id), "cart_version": cart["cart_version"]},
    ).json()

    assert body["cart"]["cart_version"] == body["cart_version"]
    assert body["approved_total"] == body["cart"]["total"]


def test_the_request_has_no_field_for_a_total_the_client_computed(api, session_id, case):
    """`expected_total` is a *string* the client says it rendered, not an amount
    it computed. A float would already have been rounded by its parser."""
    cart = _add(api, session_id, case)

    response = api.post(
        "/api/cart/approve",
        json={
            "session_id": str(session_id),
            "cart_version": cart["cart_version"],
            "subtotal": "1.00",
        },
    )

    assert response.status_code == 422


def test_changing_the_cart_after_approval_supersedes_it(api, session, session_id, case):
    """ADR-007 invalidation rule 1, end to end."""
    cart = _add(api, session_id, case)
    api.post(
        "/api/cart/approve",
        json={"session_id": str(session_id), "cart_version": cart["cart_version"]},
    )

    _add(api, session_id, case)

    live = session.execute(
        text("SELECT count(*) FROM approvals WHERE cart_id = :c AND status = 'APPROVED'"),
        {"c": cart["cart_id"]},
    ).scalar_one()
    assert live == 0


def test_approving_a_cart_that_does_not_exist_is_a_404(api, session_id):
    response = api.post(
        "/api/cart/approve", json={"session_id": str(session_id), "cart_version": 1}
    )

    assert response.status_code == 404
