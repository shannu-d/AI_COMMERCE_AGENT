"""`request_approval` — the tool that asks and cannot answer (M8; ADR-007, P§9).

This is the tool whose name most suggests it can do the thing the architecture
forbids, so the tests are mostly about the gap between asking and granting.

The structural assertions matter more than the behavioural ones. A test that
called the tool and checked the row came back `PENDING` would pass against an
implementation that wrote `APPROVED` under some other condition. A test that
asserts the service method has no `status` parameter passes only against an
implementation where writing `APPROVED` from here is impossible.
"""

from __future__ import annotations

import inspect
from datetime import UTC, datetime

import pytest

from app.agent.context import TurnMemory
from app.agent.errors import ToolError, ToolErrorCode
from app.agent.tools.approval import request_approval
from app.agent.tools.cart import propose_cart
from app.domain.commerce import ApprovalStatus
from app.domain.conversation import ConversationState
from app.llm.tool_schemas import TOOL_SCHEMAS, ProposeCartArgs, RequestApprovalArgs, RiskTier
from app.services.approval_service import ApprovalService
from tests.agent.conftest import SESSION_ID, make_variant


@pytest.fixture
def turn() -> TurnMemory:
    return TurnMemory(session_id=SESSION_ID)


@pytest.fixture
def filled_cart(context, turn, carts):
    """A cart with one real-shaped line, proposed the way the agent would."""
    case = make_variant(sku="CASE-IP16-BLK", price="999.00")
    carts.variants = {case.id: case}
    propose_cart(
        context, turn, ProposeCartArgs(items=[{"variant_id": str(case.id), "quantity": 1}])
    )
    return case


# --------------------------------------------------------------------------
# It asks
# --------------------------------------------------------------------------


def test_it_records_a_pending_approval(context, turn, filled_cart, approvals):
    result = request_approval(context, turn, RequestApprovalArgs())

    assert result["approval"]["status"] == ApprovalStatus.PENDING.value
    assert len(approvals.requested) == 1


def test_it_moves_the_conversation_to_waiting_for_approval(context, turn, filled_cart, sessions):
    request_approval(context, turn, RequestApprovalArgs())

    assert sessions.state is ConversationState.WAITING_FOR_APPROVAL


def test_it_surfaces_the_authoritative_cart(context, turn, filled_cart):
    """Re-read at this instant, not taken from what `propose_cart` returned
    earlier in the turn - a later call may have changed it."""
    result = request_approval(context, turn, RequestApprovalArgs())

    assert result["total"] == "999.00"
    assert result["items"][0]["sku"] == "CASE-IP16-BLK"


def test_the_result_says_it_is_awaiting_the_buyer(context, turn, filled_cart):
    result = request_approval(context, turn, RequestApprovalArgs())

    assert result["awaiting_user_confirmation"] is True
    assert "not approval" in result["note"].lower()


# --------------------------------------------------------------------------
# It cannot answer
# --------------------------------------------------------------------------


def test_the_service_method_it_calls_has_no_status_parameter():
    """ADR-007's central guarantee, and the reason this tool is safe to expose.

    `request_approval` is safe not because it chooses not to write APPROVED, but
    because the only method it can reach has no argument through which APPROVED
    could arrive. Enforced by the type system and by this test, not by the
    system prompt.
    """
    parameters = set(inspect.signature(ApprovalService.request).parameters)

    assert "status" not in parameters
    assert parameters == {"self", "session_id", "cart"}


def test_the_tool_never_produces_an_approved_status(context, turn, filled_cart, approvals):
    result = request_approval(context, turn, RequestApprovalArgs())

    assert result["approval"]["status"] != ApprovalStatus.APPROVED.value
    assert all(row.status is ApprovalStatus.PENDING for row in approvals.requested)


def test_the_recorded_approval_authorizes_nothing(context, turn, filled_cart, approvals):
    """P§9: the agent asking is not the buyer answering."""
    request_approval(context, turn, RequestApprovalArgs())

    assert approvals.requested[0].authorizes(datetime.now(UTC)) is False


def test_the_argument_schema_has_no_field_that_could_express_approval():
    """A model cannot say "and they said yes" because there is nowhere to say it."""
    fields = set(RequestApprovalArgs.model_fields)

    assert not any(
        word in field.lower() for field in fields for word in ("approve", "confirm", "consent")
    )


def test_the_tool_module_never_names_the_approved_status():
    """The crudest guard, and worth having: the string does not appear."""
    from app.config import BACKEND_DIR

    source = (BACKEND_DIR / "app/agent/tools/approval.py").read_text(encoding="utf-8")

    assert "ApprovalStatus.APPROVED" not in source
    assert '"APPROVED"' not in source


# --------------------------------------------------------------------------
# What it refuses
# --------------------------------------------------------------------------


def test_an_empty_cart_cannot_be_confirmed(context, turn):
    with pytest.raises(ToolError) as error:
        request_approval(context, turn, RequestApprovalArgs())

    assert error.value.code is ToolErrorCode.INVALID_ARGUMENTS


def test_a_turn_with_no_session_cannot_ask(context, filled_cart):
    with pytest.raises(LookupError):
        request_approval(context, TurnMemory(session_id=None), RequestApprovalArgs())


def test_it_is_medium_tier():
    """A§23. It writes state, so the executor requires an established session."""
    assert TOOL_SCHEMAS["request_approval"].tier is RiskTier.MEDIUM
