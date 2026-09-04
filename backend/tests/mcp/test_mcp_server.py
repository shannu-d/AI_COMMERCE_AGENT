"""The MCP surface (ADR-024).

These tests drive the FastMCP tools the way an external AI buyer would — through
`call_tool` — against the seeded catalogue and a real database. The suite is
hermetic at the payment boundary (tests/conftest.py blanks the Razorpay keys),
so `authorize_and_pay` reaches an internal `ORDER_CREATED` and stops there; the
live provider order is covered by the browser path's own live verification.

The property under test is that the commerce invariant survives the new surface:
a quote moves no money, authorization is a distinct call that must carry the
exact amount, and a wrong amount is refused with a reason code rather than
charged.
"""

from __future__ import annotations

import asyncio
import json

import pytest
from sqlalchemy.orm import Session, sessionmaker

from app.mcp.server import build_server

pytestmark = pytest.mark.requires_db


@pytest.fixture
def mcp_sessionmaker(seeded_engine):
    """A sessionmaker whose sessions all share one rolled-back transaction.

    The MCP tools open and commit their own unit-of-work sessions; this lets
    them do that against the seeded schema while nothing survives the test
    (the same `create_savepoint` trick the `session` fixture uses).
    """
    connection = seeded_engine.connect()
    outer = connection.begin()
    maker = sessionmaker(
        bind=connection,
        join_transaction_mode="create_savepoint",
        expire_on_commit=False,
        future=True,
        class_=Session,
    )
    try:
        yield maker
    finally:
        outer.rollback()
        connection.close()


@pytest.fixture
def server(mcp_sessionmaker):
    return build_server(sessionmaker=mcp_sessionmaker)


def _call(server, name: str, args: dict) -> dict:
    async def run() -> dict:
        result = await server.call_tool(name, args)
        content = result[0] if isinstance(result, tuple) else result
        for part in content:
            if hasattr(part, "text"):
                return json.loads(part.text)
        raise AssertionError(f"no text content from {name}")

    return asyncio.run(run())


def test_read_tools_are_grounded(server) -> None:
    cats = _call(server, "list_categories", {})
    assert cats["merchant"] == "EASY BUY"
    assert any(c["slug"] == "phone_case" for c in cats["categories"])

    found = _call(server, "search_catalog", {"query": "case", "category": "phone_case"})
    for row in found["results"]:
        assert isinstance(row["price"], str)  # money is a string
        assert row["reason"]  # the label comes from the ranking engine


def test_compatibility_is_resolved_not_guessed(server) -> None:
    ok = _call(server, "get_compatible_products", {"device": "iPhone 16"})
    assert ok["resolved"] is True
    assert ok["device"] == "iphone_16"

    unknown = _call(server, "get_compatible_products", {"device": "Nokia 3310"})
    assert unknown["resolved"] is False  # ask the buyer, never an empty match


def test_quote_moves_no_money_and_totals_are_the_merchants(server) -> None:
    quote = _call(server, "create_quote", {"items": [{"sku": "CASE-IP16-BLK", "quantity": 2}]})
    assert quote["quote_reference"].count(":") == 2
    assert quote["currency"] == "INR"
    assert quote["total"] == "1998.00"  # 2 x 999.00, computed server-side


def test_authorization_requires_the_exact_amount(server) -> None:
    quote = _call(server, "create_quote", {"items": [{"sku": "CASE-IP16-BLK", "quantity": 1}]})
    wrong = _call(
        server,
        "authorize_and_pay",
        {"quote_reference": quote["quote_reference"], "authorized_amount": "1.00"},
    )
    assert wrong["status"] == "rejected"
    assert wrong["code"] == "TOTAL_CHANGED"
    assert wrong["current_total"] == quote["total"]


def test_a_correct_authorization_creates_an_internal_order(server) -> None:
    quote = _call(server, "create_quote", {"items": [{"sku": "CASE-IP16-BLK", "quantity": 1}]})
    ok = _call(
        server,
        "authorize_and_pay",
        {
            "quote_reference": quote["quote_reference"],
            "authorized_amount": quote["total"],
            "buyer_reference": "test-ai-buyer",
        },
    )
    # Hermetic: no provider reached, so the order stops at the state ADR-011
    # commits before calling Razorpay.
    assert ok["status"] in {"authorized", "order_created_payment_pending"}
    assert ok["order_id"]

    status = _call(server, "get_order_status", {"order_id": ok["order_id"]})
    assert status["paid"] is False
    assert status["status"] in {"ORDER_CREATED", "RAZORPAY_ORDER_CREATED"}


def test_unknown_sku_is_refused(server) -> None:
    from mcp.server.fastmcp.exceptions import ToolError

    with pytest.raises(ToolError, match="VARIANT_NOT_FOUND"):
        _call(server, "create_quote", {"items": [{"sku": "NOT-A-SKU", "quantity": 1}]})


def test_catalog_resource_is_a_full_feed(server) -> None:
    feed = json.loads(asyncio.run(server.read_resource("easybuy://catalog"))[0].content)
    assert feed["merchant"] == "EASY BUY"
    assert feed["count"] == len(feed["variants"]) > 100
