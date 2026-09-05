"""The merchant dashboard API — `/api/merchant/*`.

Against a real database. The route layer's job is thin: resolve the merchant
server-side, call the service, shape the response, map `MerchantError` to a
status code. The properties under test:

* the merchant is never taken from the request — there is no field for it;
* a create/edit round-trips through the read API and the storefront;
* money is a string in and out, and a JSON number is a 422;
* `/overview` numbers are the real aggregates;
* an order list/detail is read-only and merchant-scoped.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.db.models import Category, Inventory, Product, ProductVariant
from app.db.session import get_db
from app.identifiers import DEFAULT_MERCHANT_ID
from app.main import create_app

pytestmark = pytest.mark.requires_db


@pytest.fixture
def api(session: Session, merchant_headers: dict[str, str]) -> TestClient:
    """A client already signed in as an administrator of the seeded merchant.

    Authentication is the *default* for this module because every route here
    requires it (ADR-023). The unauthenticated and wrong-role cases are proved
    explicitly at the bottom of the file rather than by omission.
    """
    app = create_app()
    app.dependency_overrides[get_db] = lambda: session
    return TestClient(app, headers=merchant_headers)


@pytest.fixture
def rival_variant(session: Session, rival_merchant: uuid.UUID) -> ProductVariant:
    mid = rival_merchant
    cat = Category(id=uuid.uuid4(), merchant_id=mid, name="W", slug="rival_widgets")
    session.add(cat)
    session.flush()
    prod = Product(
        id=uuid.uuid4(),
        merchant_id=mid,
        category_id=cat.id,
        name="Rival W",
        slug="rival_w",
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
        sku="RIVAL-X",
        name="D",
        price=Decimal("9.00"),
        currency="INR",
        attributes={},
        is_active=True,
    )
    session.add(var)
    session.flush()
    session.add(Inventory(id=uuid.uuid4(), variant_id=var.id, quantity=5, reserved_quantity=0))
    session.flush()
    return var


# -- overview ---------------------------------------------------------


def test_overview_is_real_aggregates(api: TestClient, catalog_seed) -> None:
    """Counted from the seed file, not from a number typed here.

    The literals this test used to carry went stale the moment the catalogue
    grew, and a stale literal fails the application for being correct.
    """
    body = api.get("/api/merchant/overview").json()
    assert body["total_products"] == len(catalog_seed.products)
    assert body["total_variants"] == catalog_seed.variant_count
    assert body["category_count"] == len(catalog_seed.categories)
    assert body["out_of_stock_variants"] >= 9
    assert Decimal(body["revenue"]) >= 0
    assert body["currency"] == "INR"


# -- products list --------------------------------------------------


def test_products_list_paginates(api: TestClient, catalog_seed) -> None:
    first = api.get("/api/merchant/products", params={"limit": 10, "offset": 0}).json()
    assert first["total"] == catalog_seed.variant_count
    assert len(first["items"]) == 10
    second = api.get("/api/merchant/products", params={"limit": 10, "offset": 10}).json()
    assert {i["sku"] for i in first["items"]}.isdisjoint({i["sku"] for i in second["items"]})


def test_products_list_filters_by_category_and_stock(api: TestClient) -> None:
    tees = api.get("/api/merchant/products", params={"category": "smartphone", "limit": 100}).json()
    assert tees["total"] > 0
    assert {i["category"] for i in tees["items"]} == {"smartphone"}

    oos = api.get(
        "/api/merchant/products", params={"stock_status": "OUT_OF_STOCK", "limit": 100}
    ).json()
    assert all(i["stock_status"] == "OUT_OF_STOCK" for i in oos["items"])
    assert oos["total"] >= 9


# -- create / edit round-trip -----------------------------------


def test_create_product_round_trips_to_the_storefront(api: TestClient) -> None:
    payload = {
        "name": "Merino Beanie Test",
        "category": "headphone",
        "description": "warm",
        "attributes": {"material": "merino"},
        "tags": ["hat"],
        "variants": [{"sku": "API-BEANIE-BLK", "name": "Black", "price": "1099.00", "quantity": 4}],
    }
    created = api.post("/api/merchant/products", json=payload)
    assert created.status_code == 201, created.text
    slug = created.json()["slug"]
    assert slug == "merino_beanie_test"

    # The storefront read API now returns it, at the price given.
    shop = api.get(f"/api/products/{slug}").json()
    assert shop["variants"][0]["price"] == "1099.00"
    assert shop["variants"][0]["sku"] == "API-BEANIE-BLK"


def test_create_product_rejects_a_json_number_price_with_422(api: TestClient) -> None:
    r = api.post(
        "/api/merchant/products",
        json={
            "name": "X",
            "category": "smartphone",
            "variants": [{"sku": "X-NUM-1", "name": "X", "price": 10.5, "quantity": 1}],
        },
    )
    assert r.status_code == 422


def test_unknown_field_in_a_request_is_rejected(api: TestClient) -> None:
    r = api.post(
        "/api/merchant/products",
        json={"name": "X", "category": "smartphone", "surprise": True},
    )
    assert r.status_code == 422


def test_price_update_flows_to_storefront_and_would_flow_to_the_agent(api: TestClient) -> None:
    # Find a charger variant via the merchant list, change its price, read it back
    # through the buyer-facing product route (the same CatalogService the agent
    # tools use).
    listing = api.get("/api/merchant/products", params={"category": "charger", "limit": 100}).json()
    row = next(i for i in listing["items"] if i["sku"] == "CHARGER-20W")
    r = api.patch(f"/api/merchant/variants/{row['variant_id']}", json={"price": "1249.00"})
    assert r.status_code == 200

    shop = api.get("/api/products", params={"category": "charger", "limit": 60}).json()
    shop_row = next(i for i in shop["items"] if i["sku"] == "CHARGER-20W")
    assert shop_row["price"] == "1249.00"


def test_stock_change_is_reflected_in_availability(api: TestClient) -> None:
    listing = api.get("/api/merchant/products", params={"q": "BUDS-LITE", "limit": 5}).json()
    vid = listing["items"][0]["variant_id"]
    r = api.patch(f"/api/merchant/inventory/{vid}", json={"quantity": 0})
    assert r.status_code == 200
    assert r.json()["stock_status"] == "OUT_OF_STOCK"

    shop = api.get("/api/products", params={"q": "SonicBuds Lite", "limit": 5}).json()
    lite = next(i for i in shop["items"] if i["sku"] == "BUDS-LITE")
    assert lite["stock_status"] == "OUT_OF_STOCK"


def test_archive_then_restore(api: TestClient) -> None:
    listing = api.get("/api/merchant/products", params={"q": "GuardGlass Privacy"}).json()
    pid = listing["items"][0]["product_id"]
    assert api.post(f"/api/merchant/products/{pid}/archive").status_code == 200
    assert api.get("/api/products/guardglass_privacy").status_code == 404
    assert api.post(f"/api/merchant/products/{pid}/restore").status_code == 200
    assert api.get("/api/products/guardglass_privacy").status_code == 200


# -- categories ---------------------------------------------------


def test_create_category(api: TestClient) -> None:
    r = api.post("/api/merchant/categories", json={"name": "Projectors", "parent": "electronics"})
    assert r.status_code == 201
    assert r.json()["slug"] == "projectors"
    assert any(c["slug"] == "projectors" for c in api.get("/api/merchant/categories").json())


# -- MERCHANT ISOLATION -------------------------------------------


def test_a_real_id_for_another_merchants_variant_is_not_found(
    api: TestClient, rival_variant: ProductVariant
) -> None:
    r = api.patch(f"/api/merchant/variants/{rival_variant.id}", json={"price": "1.00"})
    assert r.status_code == 404
    r2 = api.patch(f"/api/merchant/inventory/{rival_variant.id}", json={"quantity": 99})
    assert r2.status_code == 404


def test_another_merchants_product_is_absent_from_the_list(
    api: TestClient, rival_variant: ProductVariant
) -> None:
    body = api.get("/api/merchant/products", params={"q": "RIVAL-X", "limit": 100}).json()
    assert body["items"] == []


# -- orders ------------------------------------------------------


def test_orders_list_is_read_only_and_scoped(api: TestClient, session: Session) -> None:
    body = api.get("/api/merchant/orders").json()
    assert set(body) == {"items", "total", "limit", "offset"}
    # No orders in a fresh rolled-back DB; the shape is still right.
    assert isinstance(body["items"], list)

    # A random order id is a 404, not another merchant's order.
    r = api.get(f"/api/merchant/orders/{uuid.uuid4()}")
    assert r.status_code == 404


def test_the_merchant_api_has_no_field_for_a_merchant_id(api: TestClient) -> None:
    """A client cannot name a merchant, so it cannot name another one."""
    r = api.post(
        "/api/merchant/products",
        json={"name": "X", "category": "smartphone", "merchant_id": str(uuid.uuid4())},
    )
    assert r.status_code == 422  # extra="forbid"


# -- AUTHENTICATION AND ROLE ---------------------------------------
#
# `api` is signed in as the seeded merchant, so every test above proves the
# happy path. These prove the closed ones, and they use a *bare* client so
# there is no chance a header leaks in from the fixture.


@pytest.fixture
def anon(session: Session) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_db] = lambda: session
    return TestClient(app)


MERCHANT_ROUTES = [
    ("GET", "/api/merchant/overview"),
    ("GET", "/api/merchant/products"),
    ("GET", "/api/merchant/categories"),
    ("GET", "/api/merchant/inventory"),
    ("GET", "/api/merchant/orders"),
    ("GET", "/api/merchant/me"),
]


@pytest.mark.parametrize(("method", "path"), MERCHANT_ROUTES)
def test_every_merchant_route_refuses_an_anonymous_caller(
    anon: TestClient, method: str, path: str
) -> None:
    assert anon.request(method, path).status_code == 401


@pytest.mark.parametrize(("method", "path"), MERCHANT_ROUTES)
def test_every_merchant_route_refuses_a_customer(
    anon: TestClient, customer_headers: dict[str, str], method: str, path: str
) -> None:
    """A valid token is not authority. A shopper is 403, not 401 — they are
    authenticated, just not an administrator."""
    assert anon.request(method, path, headers=customer_headers).status_code == 403


def test_a_garbage_token_is_anonymous_not_an_error(anon: TestClient) -> None:
    r = anon.get("/api/merchant/overview", headers={"Authorization": "Bearer not-a-token"})
    assert r.status_code == 401


def test_me_reports_the_merchant_from_the_token_not_the_request(api: TestClient) -> None:
    body = api.get("/api/merchant/me").json()
    assert body["role"] == "MERCHANT"
    assert body["merchant_id"] == str(DEFAULT_MERCHANT_ID)
    assert body["merchant_name"]


# -- CROSS-MERCHANT ------------------------------------------------


def test_a_rival_administrator_sees_none_of_the_seeded_catalogue(
    anon: TestClient, rival_merchant_headers: dict[str, str]
) -> None:
    """Merchant B's token reaches Merchant B's data and nothing else — the
    scope comes from `users.merchant_id`, which no request can influence."""
    body = anon.get("/api/merchant/products", headers=rival_merchant_headers).json()
    assert body["total"] == 0

    overview = anon.get("/api/merchant/overview", headers=rival_merchant_headers).json()
    assert overview["total_products"] == 0
    assert overview["total_variants"] == 0


def test_a_rival_administrator_cannot_edit_a_seeded_variant(
    anon: TestClient,
    api: TestClient,
    rival_merchant_headers: dict[str, str],
) -> None:
    mine = api.get("/api/merchant/inventory", params={"limit": 1}).json()["items"][0]
    r = anon.patch(
        f"/api/merchant/variants/{mine['variant_id']}",
        json={"price": "1.00"},
        headers=rival_merchant_headers,
    )
    assert r.status_code == 404  # not found, never "forbidden" — no existence oracle
