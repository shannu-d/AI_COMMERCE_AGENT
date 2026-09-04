"""The read-only catalog routes.

Against a real database, because the whole point of these routes is that a
browsed product is a row PostgreSQL holds rather than something the UI invented.
A test against a double would prove nothing about the property that matters.

The contract under test is mostly about *restraint*: these routes read, they
never write, they never rank, and no model is anywhere near them.
"""

from __future__ import annotations

from decimal import Decimal

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


# -- categories -------------------------------------------------------------


def test_categories_are_the_merchants_own(api: TestClient) -> None:
    body = api.get("/api/categories").json()
    slugs = {c["slug"] for c in body}
    # The seed's real vocabulary. A wrong slug here looks like a broken tool
    # elsewhere in the system, so it is worth pinning.
    assert {"phone_case", "charger", "usb_cable", "earbuds"} <= slugs


# -- listing ----------------------------------------------------------------


def test_a_listing_returns_one_row_per_sellable_variant(api: TestClient) -> None:
    body = api.get("/api/products", params={"limit": 60}).json()
    # `total` is every matching variant; `items` is one page of them. The
    # catalogue is now larger than a page, so the invariant is the page size
    # and the no-duplicate-variant rule, not "everything fits at once".
    assert len(body["items"]) == min(body["total"], 60)
    skus = [i["sku"] for i in body["items"]]
    assert len(skus) == len(set(skus)), "a variant appeared twice"


def test_a_category_listing_returns_one_row_per_sellable_variant(api: TestClient) -> None:
    """The whole-catalogue check above, scoped so the page holds every row."""
    body = api.get("/api/products", params={"category": "phone_case", "limit": 60}).json()
    assert body["total"] == len(body["items"])
    skus = [i["sku"] for i in body["items"]]
    assert len(skus) == len(set(skus))


def test_every_price_is_a_fixed_scale_string(api: TestClient) -> None:
    """ADR-008. A JSON number here would already have been through float."""
    for item in api.get("/api/products", params={"limit": 60}).json()["items"]:
        assert isinstance(item["price"], str)
        assert Decimal(item["price"]) == Decimal(item["price"]).quantize(Decimal("0.01"))


def test_stock_status_is_present_for_every_row(api: TestClient) -> None:
    for item in api.get("/api/products", params={"limit": 60}).json()["items"]:
        assert item["stock_status"] in {"IN_STOCK", "LOW_STOCK", "OUT_OF_STOCK"}


def test_a_category_filter_narrows_the_result(api: TestClient) -> None:
    everything = api.get("/api/products", params={"limit": 60}).json()["total"]
    cases = api.get("/api/products", params={"category": "phone_case", "limit": 60}).json()
    assert 0 < cases["total"] < everything
    assert {i["category"] for i in cases["items"]} == {"phone_case"}


def test_a_budget_filter_excludes_dearer_variants(api: TestClient) -> None:
    body = api.get("/api/products", params={"max_price": "999.00", "limit": 60}).json()
    assert body["total"] > 0
    assert all(Decimal(i["price"]) <= Decimal("999.00") for i in body["items"])


def test_price_sorting_is_deterministic_in_both_directions(api: TestClient) -> None:
    # Scoped to one category so a single page holds every matching row — with
    # the larger catalogue an unscoped page is a *slice*, and the cheapest 60
    # are not the reverse of the dearest 60.
    p = {"category": "phone_case", "limit": 60}
    asc = api.get("/api/products", params={**p, "sort": "price_asc"}).json()["items"]
    desc = api.get("/api/products", params={**p, "sort": "price_desc"}).json()["items"]
    prices = [Decimal(i["price"]) for i in asc]
    assert prices == sorted(prices)
    assert [Decimal(i["price"]) for i in desc] == sorted(prices, reverse=True)

    # And each direction of an unscoped page is at least internally monotonic.
    big_asc = [
        Decimal(i["price"])
        for i in api.get("/api/products", params={"sort": "price_asc", "limit": 60}).json()["items"]
    ]
    assert big_asc == sorted(big_asc)


def test_the_same_request_twice_gives_the_same_order(api: TestClient) -> None:
    """No randomness, no clock: a listing is reproducible."""
    params = {"sort": "price_asc", "limit": 60}
    first = [i["sku"] for i in api.get("/api/products", params=params).json()["items"]]
    second = [i["sku"] for i in api.get("/api/products", params=params).json()["items"]]
    assert first == second


def test_limit_is_bounded(api: TestClient) -> None:
    assert api.get("/api/products", params={"limit": 500}).status_code == 422


def test_an_unknown_category_is_not_found(api: TestClient) -> None:
    response = api.get("/api/products", params={"category": "no_such_category"})
    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "PRODUCT_NOT_FOUND"


def test_a_malformed_budget_fails_loudly_rather_than_being_ignored(api: TestClient) -> None:
    """A budget that silently stops applying is worse than one that errors."""
    response = api.get("/api/products", params={"max_price": "cheap"})
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "VALIDATION_ERROR"


# -- detail -----------------------------------------------------------------


def test_product_detail_carries_every_variant(api: TestClient) -> None:
    listing = api.get("/api/products", params={"limit": 60}).json()["items"]
    slug = listing[0]["product_slug"]
    body = api.get(f"/api/products/{slug}").json()

    assert body["product"]["slug"] == slug
    assert len(body["variants"]) >= 1
    for variant in body["variants"]:
        assert isinstance(variant["price"], str)
        assert variant["stock_status"] in {"IN_STOCK", "LOW_STOCK", "OUT_OF_STOCK"}


def test_an_unknown_product_is_not_found(api: TestClient) -> None:
    response = api.get("/api/products/no-such-product")
    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "PRODUCT_NOT_FOUND"


# -- what these routes must never do ----------------------------------------


def test_the_catalog_routes_expose_no_write_verb() -> None:
    """Browsing cannot change anything. A POST here would be a new door."""
    app = create_app()
    for route in app.routes:
        path = getattr(route, "path", "")
        if path.startswith("/api/products") or path == "/api/categories":
            assert set(getattr(route, "methods", set())) <= {"GET", "HEAD"}


def test_no_listing_row_carries_a_ranking_score(api: TestClient) -> None:
    """Scores belong to the ranking engine and reach a buyer only via the agent."""
    for item in api.get("/api/products", params={"limit": 60}).json()["items"]:
        assert "score" not in item
        assert "rank" not in item
        assert "reason" not in item


def test_the_catalog_route_module_imports_no_model_code() -> None:
    """These handlers are on the deterministic side of the boundary (ADR-015)."""
    import ast
    import pathlib

    source = pathlib.Path("app/api/routes/catalog.py").read_text(encoding="utf-8")
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            names = (getattr(node, "module", "") or "") + " ".join(a.name for a in node.names)
            assert "app.llm" not in names
            assert "app.agent.runtime" not in names
