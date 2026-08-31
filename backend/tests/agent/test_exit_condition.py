"""M5's exit condition, as a standing test.

`02-dependency-map.md` states it in one line:

> "Find me a case for iPhone 16 under ₹1500" returns grounded Top-3

This runs the whole path for real — a real PostgreSQL, the real seeded
CircuitCraft catalog, the real services, the real compatibility resolver, the
real ranking engine and the real `POST /api/chat` contract. The only thing faked
is the model, at the `LLMClient` protocol, because ADR-015 forbids any test from
calling a live one and because what the milestone has to prove is that the
*application* grounds the answer, not that a model phrases it well.

The distinction matters and is worth being precise about. A real model would
choose which tool to call from the buyer's sentence; here the tool call is
scripted. Everything after that point — resolving "iPhone 16" to `iphone_16`,
eliminating the iPhone 15 case and the out-of-stock variant, applying the ₹1,500
ceiling, ranking what survives, and refusing to let the model's prose alter any
of it — is the code under test.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy.orm import Session

from app.agent.context import AgentContext
from app.agent.registry import build_registry
from app.agent.runtime import AgentRuntime
from app.domain.conversation import ConversationState
from tests.agent.conftest import FakeClient, text_reply, tool_reply

pytestmark = pytest.mark.requires_db

BUDGET = Decimal("1500.00")


@pytest.fixture
def runtime_and_session(session: Session, merchant_id):
    """A real runtime over a real catalog, with the model scripted."""

    def build(*responses, **kwargs):
        context = AgentContext.from_session(session, merchant_id)
        conversation = context.sessions.create(merchant_id)
        runtime = AgentRuntime(FakeClient(*responses), build_registry(), context, **kwargs)
        return runtime, conversation.id, context

    return build


# --------------------------------------------------------------------------
# The exit condition
# --------------------------------------------------------------------------


def test_the_worked_request_returns_a_grounded_top_three(runtime_and_session):
    """ "Find me a case for iPhone 16 under ₹1500" -> grounded Top-3."""
    runtime, session_id, _ = runtime_and_session(
        tool_reply(
            "get_compatible_products",
            {"device": "iPhone 16", "category": "phone_case", "max_price": 1500},
        ),
        text_reply("Here are three iPhone 16 cases under ₹1,500."),
        top_k=3,
    )

    result = runtime.run_turn(session_id, "Find me a case for iPhone 16 under ₹1500")

    assert result.state is ConversationState.RECOMMENDING
    assert result.error is None
    assert 1 <= len(result.recommendations) <= 3

    for row in result.recommendations:
        # Grounded: every field came out of PostgreSQL this turn.
        assert row["sku"]
        assert Decimal(row["price"]) <= BUDGET
        assert row["currency"] == "INR"
        assert row["category"] == "phone_case"
        # RULE 5: nothing unpurchasable is offered as a match.
        assert row["stock_status"] in {"IN_STOCK", "LOW_STOCK"}
        # ADR-004, closing A7: the label is the engine's, not the model's.
        assert row["reason"] in {
            "Best overall",
            "Best price",
            "Closest match to your requirements",
        }


def test_every_result_is_actually_compatible_with_the_iphone_16(runtime_and_session):
    """ADR-005: compatibility eliminates and is never relaxed.

    The seed catalog contains an iPhone 15 case on purpose, priced so that a
    ranker weighted toward price would want it. It must not appear.
    """
    runtime, session_id, context = runtime_and_session(
        tool_reply(
            "get_compatible_products",
            {"device": "iPhone 16", "category": "phone_case", "max_price": 1500},
        ),
        text_reply("Here you are."),
    )

    result = runtime.run_turn(session_id, "a case for my iPhone 16 under 1500")

    resolution = context.compatibility.resolve_target("iPhone 16")
    compatible = context.compatibility.compatible_product_ids(context.merchant_id, resolution)
    for row in result.recommendations:
        assert row["product_id"] in {str(pid) for pid in compatible}


def test_an_unknown_device_asks_the_buyer_instead_of_guessing(runtime_and_session):
    """ADR-003. `pixel_9` is seeded as a *resolvable* device with no compatible
    products, precisely so that "we have nothing" and "we did not understand"
    stay distinguishable. This asserts the second one."""
    runtime, session_id, _ = runtime_and_session(
        tool_reply("get_compatible_products", {"device": "Nokia N95", "category": "phone_case"}),
        text_reply("Which phone model do you have?"),
    )

    result = runtime.run_turn(session_id, "a case for my Nokia N95")

    assert result.recommendations == []
    assert result.state is ConversationState.TOOL_ERROR


def test_a_resolvable_device_with_no_products_is_a_no_match_not_a_question(
    runtime_and_session,
):
    """The other half of the same distinction. `pixel_9` resolves; the catalog
    simply has nothing for it. That is a legitimate answer (R§14)."""
    runtime, session_id, _ = runtime_and_session(
        tool_reply("get_compatible_products", {"device": "Pixel 9", "category": "phone_case"}),
        text_reply("I don't have cases for the Pixel 9."),
    )

    result = runtime.run_turn(session_id, "a case for my Pixel 9")

    # The tool succeeded — it resolved the device and found nothing — so this is
    # not a TOOL_ERROR. There is simply nothing to recommend.
    assert result.recommendations == []
    assert result.state is ConversationState.NEED_CLARIFICATION


def test_nothing_over_the_budget_is_presented_as_a_match(runtime_and_session):
    """R§8, D§30: a budget is a hard ceiling, not a preference."""
    runtime, session_id, _ = runtime_and_session(
        tool_reply(
            "get_compatible_products",
            {"device": "iPhone 16", "category": "phone_case", "max_price": 500},
        ),
        text_reply("Here is what fits."),
    )

    result = runtime.run_turn(session_id, "a case for iPhone 16 under 500")

    assert all(Decimal(row["price"]) <= Decimal("500") for row in result.recommendations)


def test_the_model_cannot_add_a_product_to_a_real_result(runtime_and_session):
    """The grounding property, against a real catalog.

    The model is scripted to name a product that does not exist. The prose says
    what it says; the structured half carries only what the ranker returned.
    """
    runtime, session_id, _ = runtime_and_session(
        tool_reply(
            "get_compatible_products",
            {"device": "iPhone 16", "category": "phone_case", "max_price": 1500},
        ),
        text_reply("I also recommend the NovaShell X9 at ₹499, SKU NOVA-X9."),
    )

    result = runtime.run_turn(session_id, "a case for iPhone 16 under 1500")

    assert all(row["sku"] != "NOVA-X9" for row in result.recommendations)
    assert "NOVA-X9" not in str(result.recommendations)


def test_a_fabricated_sku_reaches_no_product(runtime_and_session):
    """ADR-009's named M5 test, end to end against the real catalog."""
    runtime, session_id, _ = runtime_and_session(
        tool_reply("get_product", {"sku": "CASE-IP16-INVENTED"}),
        text_reply("I couldn't find that one."),
    )

    result = runtime.run_turn(session_id, "tell me about CASE-IP16-INVENTED")

    assert result.recommendations == []
    assert result.state is ConversationState.TOOL_ERROR


def test_the_conversation_survives_to_the_next_turn(runtime_and_session, session):
    """A§37, A§38, closing C3: the session is in PostgreSQL, so a second turn
    sees the first."""
    runtime, session_id, context = runtime_and_session(
        text_reply("Which phone do you have?"),
    )

    runtime.run_turn(session_id, "I need a case")

    history = context.sessions.history(context.merchant_id, session_id)
    assert [row.role for row in history] == ["user", "assistant"]
    assert history[0].content == "I need a case"
