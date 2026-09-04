"""`merchant_activity` — who changed the catalogue, and to what (ADR-023 §7).

The catalogue the dashboard edits is the catalogue the agent recommends from, so
"who set this price and when" has to be answerable from a record written at the
moment of the change. These tests hold that record to four properties:

* it is written by the **write**, not by a later reconstruction;
* the actor is the **authenticated** administrator and cannot be supplied;
* it is scoped to one merchant, like everything else in the dashboard;
* it **rolls back with the edit it describes** — a log of changes that never
  happened would be worse than no log.
"""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.db.models import MerchantActivity
from app.db.session import get_db
from app.main import create_app

pytestmark = pytest.mark.requires_db


@pytest.fixture
def api(session: Session, merchant_headers: dict[str, str]) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_db] = lambda: session
    return TestClient(app, headers=merchant_headers)


@pytest.fixture
def anon(session: Session) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_db] = lambda: session
    return TestClient(app)


def _log(api: TestClient) -> list[dict]:
    return api.get("/api/merchant/activity").json()["items"]


# -- the write is what writes the record ------------------------------


def test_creating_a_product_is_recorded_with_its_variants(api: TestClient) -> None:
    created = api.post(
        "/api/merchant/products",
        json={
            "name": "Activity Test Tee",
            "category": "t_shirt",
            "variants": [
                {"sku": "ACT-TEE-1", "name": "S", "price": "499.00", "quantity": 3},
            ],
        },
    )
    assert created.status_code == 201, created.text

    entry = _log(api)[0]
    assert entry["action"] == "PRODUCT_CREATED"
    assert entry["entity_type"] == "PRODUCT"
    assert entry["subject"] == "Activity Test Tee"
    assert entry["payload"]["variants"] == [{"sku": "ACT-TEE-1", "price": "499.00"}]
    # Money is a string in the log too — there is no place in this system where
    # an amount becomes a float (ADR-008).
    assert isinstance(entry["payload"]["variants"][0]["price"], str)


def test_a_price_change_records_what_it_changed_from(api: TestClient) -> None:
    listing = api.get("/api/merchant/products", params={"q": "CHARGER-20W", "limit": 5}).json()
    row = listing["items"][0]
    was = row["price"]

    assert (
        api.patch(f"/api/merchant/variants/{row['variant_id']}", json={"price": "1499.00"})
    ).status_code == 200

    entry = _log(api)[0]
    assert entry["action"] == "PRICE_CHANGED"  # not a generic VARIANT_UPDATED
    assert entry["subject"] == "CHARGER-20W"
    assert entry["payload"] == {"from": was, "to": "1499.00"}


def test_a_non_price_variant_edit_is_not_a_price_change(api: TestClient) -> None:
    listing = api.get("/api/merchant/products", params={"q": "CHARGER-20W", "limit": 5}).json()
    vid = listing["items"][0]["variant_id"]
    api.patch(f"/api/merchant/variants/{vid}", json={"name": "Renamed"})

    entry = _log(api)[0]
    assert entry["action"] == "VARIANT_UPDATED"
    assert entry["payload"]["changed"] == ["name"]


def test_a_stock_change_records_both_ends(api: TestClient) -> None:
    listing = api.get("/api/merchant/products", params={"q": "BUDS-LITE", "limit": 5}).json()
    row = listing["items"][0]
    api.patch(f"/api/merchant/inventory/{row['variant_id']}", json={"quantity": 0})

    entry = _log(api)[0]
    assert entry["action"] == "STOCK_CHANGED"
    assert entry["payload"]["from"] == row["quantity"]
    assert entry["payload"]["to"] == 0
    assert entry["payload"]["stock_status"] == "OUT_OF_STOCK"


def test_archive_and_restore_are_separate_actions(api: TestClient) -> None:
    listing = api.get("/api/merchant/products", params={"q": "GuardGlass Privacy"}).json()
    pid = listing["items"][0]["product_id"]
    api.post(f"/api/merchant/products/{pid}/archive")
    api.post(f"/api/merchant/products/{pid}/restore")

    actions = [entry["action"] for entry in _log(api)[:2]]
    assert actions == ["PRODUCT_RESTORED", "PRODUCT_ARCHIVED"]  # newest first


def test_a_category_creation_is_recorded(api: TestClient) -> None:
    api.post("/api/merchant/categories", json={"name": "Belts", "parent": "clothing"})
    entry = _log(api)[0]
    assert entry["action"] == "CATEGORY_CREATED"
    assert entry["entity_type"] == "CATEGORY"
    assert entry["subject"] == "belts"


# -- the actor is the token, never the request ------------------------


def test_the_actor_is_the_authenticated_administrator(
    api: TestClient, merchant_headers: dict[str, str]
) -> None:
    who = api.get("/api/merchant/me").json()["email"]
    api.post("/api/merchant/categories", json={"name": "Hats"})
    assert _log(api)[0]["actor_email"] == who


def test_a_request_cannot_name_an_actor(api: TestClient) -> None:
    """Every dashboard schema is `extra="forbid"`, so there is no field for it."""
    r = api.post(
        "/api/merchant/categories",
        json={"name": "Socks", "actor_email": "someone@else.test"},
    )
    assert r.status_code == 422


def test_reading_the_log_needs_a_merchant(
    anon: TestClient, customer_headers: dict[str, str]
) -> None:
    assert anon.get("/api/merchant/activity").status_code == 401
    assert anon.get("/api/merchant/activity", headers=customer_headers).status_code == 403


# -- scope and durability ---------------------------------------------


def test_one_merchants_log_is_not_anothers(
    api: TestClient, anon: TestClient, rival_merchant_headers: dict[str, str]
) -> None:
    api.post("/api/merchant/categories", json={"name": "Ties"})
    assert _log(api)  # the seeded merchant's administrator sees their entry

    rival = anon.get("/api/merchant/activity", headers=rival_merchant_headers).json()
    assert rival["total"] == 0
    assert rival["items"] == []


def test_a_refused_edit_leaves_no_entry(api: TestClient, session: Session) -> None:
    """The record shares the transaction with the change, so a rejected write
    logs nothing — a log of edits that never happened would be worse than none."""
    before = session.query(MerchantActivity).count()
    refused = api.patch(f"/api/merchant/variants/{uuid.uuid4()}", json={"price": "1.00"})
    assert refused.status_code == 404
    assert session.query(MerchantActivity).count() == before


def test_a_read_is_not_an_event(api: TestClient) -> None:
    """Only writes are logged. Logging every list request would bury the eleven
    actions that can actually change what a buyer is offered."""
    before = len(_log(api))
    api.get("/api/merchant/products", params={"limit": 5})
    api.get("/api/merchant/overview")
    api.get("/api/merchant/orders")
    assert len(_log(api)) == before


def test_the_log_can_be_filtered_by_action(api: TestClient) -> None:
    api.post("/api/merchant/categories", json={"name": "Gloves"})
    api.post(
        "/api/merchant/products",
        json={
            "name": "Filter Probe",
            "category": "t_shirt",
            "variants": [{"sku": "ACT-FILT-1", "name": "S", "price": "100.00", "quantity": 1}],
        },
    )
    body = api.get("/api/merchant/activity", params={"action": "CATEGORY_CREATED"}).json()
    assert body["total"] == 1
    assert body["items"][0]["subject"] == "gloves"
