"""`propose_cart` — the first MEDIUM-tier tool (M7; ADR-009, A§13).

The tests that matter are about the gap between "writes state" and "moves
money", because that gap is the entire justification for letting a model call
this at all.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.agent.context import TurnMemory
from app.agent.errors import ToolError, ToolErrorCode
from app.agent.executor import ToolExecutor
from app.agent.registry import build_registry
from app.agent.tools.cart import propose_cart
from app.llm.tool_schemas import TOOL_SCHEMAS, ProposeCartArgs, RiskTier
from tests.agent.conftest import SESSION_ID, make_variant


@pytest.fixture
def stocked(carts):
    """Two real-shaped variants the stub cart service can price."""
    case = make_variant(sku="CASE-IP16-BLK", price="999.00")
    charger = make_variant(sku="CHARGER-20W", price="1499.00", product_name="VoltEdge 20W")
    carts.variants = {case.id: case, charger.id: charger}
    return case, charger


@pytest.fixture
def turn() -> TurnMemory:
    return TurnMemory(session_id=SESSION_ID)


def args(*pairs) -> ProposeCartArgs:
    return ProposeCartArgs(items=[{"variant_id": str(vid), "quantity": q} for vid, q in pairs])


# --------------------------------------------------------------------------
# It computes nothing
# --------------------------------------------------------------------------


def test_the_total_is_computed_from_catalog_prices(context, turn, stocked):
    """A§13. The model supplied two ids and two integers; everything with a
    currency sign on it came from the backend."""
    case, charger = stocked

    result = propose_cart(context, turn, args((case.id, 2), (charger.id, 1)))

    assert result["total"] == "3497.00"  # 999*2 + 1499
    assert result["subtotal"] == "3497.00"


def test_the_argument_schema_has_no_money_field():
    """The structural half: there is nowhere for a model to put a price.

    A schema that accepted one would make every other guard in this file a
    matter of the handler remembering to ignore it.
    """
    fields = ProposeCartArgs.model_json_schema()["properties"]
    assert set(fields) == {"items"}

    line = ProposeCartArgs.model_fields["items"].annotation.__args__[0]
    assert set(line.model_fields) == {"variant_id", "quantity"}


def test_a_model_supplied_price_is_rejected_rather_than_ignored(context, turn, stocked):
    """`extra="forbid"`. A silently-dropped price looks honoured."""
    case, _ = stocked

    with pytest.raises(ValidationError, match="unit_price"):
        ProposeCartArgs(items=[{"variant_id": str(case.id), "quantity": 1, "unit_price": "1.00"}])


def test_money_leaves_as_a_fixed_scale_string(context, turn, stocked):
    """ADR-008, everywhere a buyer or a client can see it."""
    case, _ = stocked

    result = propose_cart(context, turn, args((case.id, 1)))

    assert result["total"] == "999.00"
    assert result["items"][0]["unit_price"] == "999.00"
    assert not isinstance(result["total"], Decimal | float | int)


# --------------------------------------------------------------------------
# It proposes; it does not authorize
# --------------------------------------------------------------------------


def test_a_proposed_cart_says_it_is_a_proposal(context, turn, stocked):
    case, _ = stocked

    result = propose_cart(context, turn, args((case.id, 1)))

    assert result["status"] == "PROPOSED"


def test_nothing_in_the_result_resembles_an_approval(context, turn, stocked):
    """A cart is a draft. An order needs an `approvals` row, and
    `orders.approval_id NOT NULL` means the database refuses otherwise."""
    case, _ = stocked

    result = propose_cart(context, turn, args((case.id, 1)))

    for forbidden in ("approved", "approval_id", "authorized", "order_id", "paid"):
        assert forbidden not in str(result).lower()


def test_the_cart_version_travels_with_the_proposal(context, turn, stocked):
    """F§13, A§27: it is what an approval will bind to, so a client that renders
    a total without it cannot tell a current confirmation from a stale one."""
    case, _ = stocked

    result = propose_cart(context, turn, args((case.id, 1)))

    assert isinstance(result["cart_version"], int)


# --------------------------------------------------------------------------
# It replaces rather than appends
# --------------------------------------------------------------------------


def test_a_second_proposal_corrects_the_first(context, turn, stocked):
    """ "Actually, just the case" must not produce a cart holding it twice."""
    case, charger = stocked
    propose_cart(context, turn, args((case.id, 1), (charger.id, 1)))

    result = propose_cart(context, turn, args((case.id, 1)))

    assert [item["sku"] for item in result["items"]] == ["CASE-IP16-BLK"]


# --------------------------------------------------------------------------
# What it refuses
# --------------------------------------------------------------------------


def test_a_variant_that_does_not_exist_is_refused(context, turn, stocked):
    with pytest.raises(ToolError) as error:
        propose_cart(context, turn, args((uuid.uuid4(), 1)))

    assert error.value.code is ToolErrorCode.VARIANT_NOT_FOUND


def test_a_malformed_variant_id_reads_as_not_found(context, turn, stocked):
    with pytest.raises(ToolError) as error:
        propose_cart(context, turn, ProposeCartArgs(items=[{"variant_id": "nope", "quantity": 1}]))

    assert error.value.code is ToolErrorCode.VARIANT_NOT_FOUND


def test_an_out_of_stock_variant_is_refused(context, turn, stocked, carts):
    """RULE 5. Nothing unpurchasable goes in a cart."""
    case, _ = stocked
    carts.unavailable.add(case.id)

    with pytest.raises(ToolError) as error:
        propose_cart(context, turn, args((case.id, 1)))

    assert error.value.code is ToolErrorCode.OUT_OF_STOCK


def test_a_turn_with_no_session_cannot_propose_anything(context, stocked):
    """A write with no established owner. The session comes from the runtime,
    never from a tool argument."""
    case, _ = stocked

    with pytest.raises(LookupError):
        propose_cart(context, TurnMemory(session_id=None), args((case.id, 1)))


# --------------------------------------------------------------------------
# The executor's tier check
# --------------------------------------------------------------------------


def test_propose_cart_is_medium_tier():
    """A§23. The tier is what the executor branches on."""
    assert TOOL_SCHEMAS["propose_cart"].tier is RiskTier.MEDIUM


def test_the_executor_refuses_a_medium_tool_in_a_turn_with_no_session(context, stocked):
    """The authorization A§22 asks for, and the only one MEDIUM needs: an owner
    for the state it is about to write."""
    case, _ = stocked
    executor = ToolExecutor(build_registry(), context, max_calls_per_turn=8)

    result = executor.execute(
        "propose_cart",
        {"items": [{"variant_id": str(case.id), "quantity": 1}]},
        TurnMemory(session_id=None),
    )

    assert result["success"] is False
    assert result["error"]["code"] == ToolErrorCode.FORBIDDEN_TOOL.value


def test_the_executor_runs_a_medium_tool_when_the_turn_has_a_session(context, turn, stocked):
    case, _ = stocked
    executor = ToolExecutor(build_registry(), context, max_calls_per_turn=8)

    result = executor.execute(
        "propose_cart", {"items": [{"variant_id": str(case.id), "quantity": 1}]}, turn
    )

    assert result["success"] is True
    assert result["result"]["total"] == "999.00"
