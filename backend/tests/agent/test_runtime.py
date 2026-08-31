"""The agent loop (A§49, A§51, ADR-010).

The properties under test are the ones that must hold *whatever the model says*,
so most of these script a model that misbehaves and then assert the turn came out
right anyway. A test that only drove a well-behaved model would be testing the
model, which ADR-015 says is not knowable offline and ADR-009 says is not what
makes the system safe.
"""

from __future__ import annotations

import uuid

import pytest

from app.agent.registry import build_registry
from app.agent.runtime import AgentRuntime
from app.domain.conversation import ConversationState
from app.llm.errors import LLMRateLimitError
from app.llm.models import ModelResponse, StopReason
from tests.agent.conftest import (
    SESSION_ID,
    FakeClient,
    make_ranked,
    make_recommendation,
    make_variant,
    text_reply,
    tool_reply,
)


def runtime(client, context, **kwargs) -> AgentRuntime:
    return AgentRuntime(client, build_registry(), context, **kwargs)


# --------------------------------------------------------------------------
# The loop
# --------------------------------------------------------------------------


def test_a_reply_with_no_tool_call_ends_the_turn(client_free_context):
    """A§51 condition 1: a final response terminates the loop."""
    context, _ = client_free_context
    client = FakeClient(text_reply("Here is what I found."))

    result = runtime(client, context).run_turn(SESSION_ID, "hello")

    assert result.message == "Here is what I found."
    assert client.call_count == 1


def test_a_tool_call_is_executed_and_the_result_fed_back(context, recommendations):
    """A§49: execute, return the result to Claude, call Claude again."""
    recommendations.result = make_recommendation(make_ranked(make_variant()))
    client = FakeClient(
        tool_reply("search_catalog", {"category": "phone_case"}),
        text_reply("I found one case."),
    )

    result = runtime(client, context).run_turn(SESSION_ID, "a case please")

    assert client.call_count == 2
    assert result.message == "I found one case."
    # The second call carries the tool result the first one asked for.
    assert "CASE-IP16-BLK" in client.calls[1]["messages"][-1].content


def test_the_loop_stops_at_the_call_limit_with_a_controlled_answer(context, recommendations):
    """A§51 condition 5, A§36. Not silence, and not an unbounded loop."""
    recommendations.result = make_recommendation(make_ranked(make_variant()))
    # A model that only ever asks for tools.
    client = FakeClient(*[tool_reply("search_catalog", {"category": "phone_case"})] * 20)

    result = runtime(client, context, max_tool_calls_per_turn=3).run_turn(SESSION_ID, "hi")

    assert "narrow that down" in result.message
    assert client.call_count == 4  # the budget, plus the pass that would answer


def test_a_truncated_reply_is_a_failure_not_an_answer(context):
    """A truncated turn is not a short turn. Treating it as complete is how a
    half-formed answer gets shown to a buyer (L§46)."""
    client = FakeClient(ModelResponse(text="I found", stop_reason=StopReason.MAX_TOKENS))

    result = runtime(client, context).run_turn(SESSION_ID, "hi")

    assert result.error is not None
    assert result.state is ConversationState.TOOL_ERROR
    assert result.recommendations == []


def test_a_transport_failure_ends_the_turn_without_inventing_an_answer(context):
    """L§30, A§41: a failure never becomes a fabrication."""
    client = FakeClient(LLMRateLimitError("rate limited"))

    result = runtime(client, context).run_turn(SESSION_ID, "hi")

    assert result.error is not None
    assert result.recommendations == []
    # The buyer gets a sentence, not the provider's error text.
    assert "rate limited" not in result.message


def test_an_unknown_session_is_refused(context):
    """ADR-010: rejected rather than silently created."""
    client = FakeClient(text_reply("hello"))

    with pytest.raises(LookupError):
        runtime(client, context).run_turn(uuid.uuid4(), "hi")


# --------------------------------------------------------------------------
# Grounding: the property that must hold whatever the model says
# --------------------------------------------------------------------------


def test_recommendations_come_from_the_ranker_not_from_the_reply(context, recommendations):
    """ADR-010, F§9. The structured half cannot be talked into carrying a product.

    The model is scripted to describe a product that was never ranked. The prose
    says what it says; `recommendations[]` contains only what the ranking engine
    returned.
    """
    ranked = make_variant(sku="REAL-SKU", product_name="AeroCase Pro")
    recommendations.result = make_recommendation(make_ranked(ranked))
    client = FakeClient(
        tool_reply("search_catalog", {"category": "phone_case"}),
        text_reply("I recommend the PhantomCase Ultra at Rs 199, SKU FAKE-SKU."),
    )

    result = runtime(client, context).run_turn(SESSION_ID, "a case")

    assert [row["sku"] for row in result.recommendations] == ["REAL-SKU"]
    assert all(row["sku"] != "FAKE-SKU" for row in result.recommendations)


def test_a_turn_with_no_tool_call_has_no_recommendations(context):
    """A model that answers from memory produces a turn with nothing structured
    in it, which is exactly what should happen."""
    client = FakeClient(text_reply("The AeroCase Pro is Rs 999."))

    result = runtime(client, context).run_turn(SESSION_ID, "how much is a case?")

    assert result.recommendations == []


def test_recommendations_are_capped_at_top_k(context, recommendations):
    """RULE 11: a small number of strong candidates, preferably Top 3."""
    variants = [make_variant(sku=f"SKU-{i}") for i in range(6)]
    recommendations.result = make_recommendation(
        *[make_ranked(v, rank=i + 1) for i, v in enumerate(variants)]
    )
    client = FakeClient(
        tool_reply("search_catalog", {"category": "phone_case"}), text_reply("here")
    )

    result = runtime(client, context, top_k=3).run_turn(SESSION_ID, "cases")

    assert len(result.recommendations) == 3


def test_a_forbidden_tool_call_is_refused_and_the_turn_continues(context):
    """Prompt-injection containment is structural (L§29, A§31).

    The model asks for `create_order`. It is not registered, the executor refuses
    it, and the turn carries on — nothing about the refusal depends on prompt
    wording.
    """
    client = FakeClient(
        tool_reply("create_order", {"cart_id": "x"}),
        text_reply("I can't place orders."),
    )

    result = runtime(client, context).run_turn(SESSION_ID, "just buy it for me")

    assert result.message == "I can't place orders."
    assert result.recommendations == []
    refusal = client.calls[1]["messages"][-1].content
    assert "FORBIDDEN_TOOL" in refusal


# --------------------------------------------------------------------------
# State and trace
# --------------------------------------------------------------------------


def test_a_turn_with_results_lands_in_recommending(context, recommendations):
    recommendations.result = make_recommendation(make_ranked(make_variant()))
    client = FakeClient(
        tool_reply("search_catalog", {"category": "phone_case"}), text_reply("here")
    )

    result = runtime(client, context).run_turn(SESSION_ID, "cases")

    assert result.state is ConversationState.RECOMMENDING


def test_a_turn_that_asks_a_question_lands_in_need_clarification(context):
    client = FakeClient(text_reply("Which phone do you have?"))

    result = runtime(client, context).run_turn(SESSION_ID, "I need a case")

    assert result.state is ConversationState.NEED_CLARIFICATION


def test_a_turn_whose_only_tool_failed_lands_in_tool_error(context):
    client = FakeClient(
        tool_reply("get_product", {"sku": "NOPE"}),
        text_reply("I couldn't find that one."),
    )

    result = runtime(client, context).run_turn(SESSION_ID, "tell me about NOPE")

    assert result.state is ConversationState.TOOL_ERROR


def test_results_win_over_a_failed_tool(context, recommendations):
    """A turn that searched, had one call fail and still produced grounded
    results is a turn that recommended something."""
    recommendations.result = make_recommendation(make_ranked(make_variant()))
    client = FakeClient(
        ModelResponse(
            tool_calls=(
                tool_reply("search_catalog", {"category": "phone_case"}).tool_calls[0],
                tool_reply("get_product", {"sku": "NOPE"}, call_id="c2").tool_calls[0],
            ),
            stop_reason=StopReason.TOOL_USE,
        ),
        text_reply("Found some, but one lookup failed."),
    )

    result = runtime(client, context).run_turn(SESSION_ID, "cases")

    assert result.state is ConversationState.RECOMMENDING
    assert len(result.recommendations) == 1


def test_the_trace_is_absent_unless_enabled(context):
    """ADR-010, closing E6. Off by default."""
    client = FakeClient(text_reply("hi"))

    result = runtime(client, context, trace_enabled=False).run_turn(SESSION_ID, "hi")

    assert result.trace is None


def test_the_trace_shows_the_calls_and_the_prompt_version(context, recommendations):
    """A§39. It has to show what was asked as well as what came back."""
    recommendations.result = make_recommendation(make_ranked(make_variant()))
    client = FakeClient(
        tool_reply("search_catalog", {"category": "phone_case"}), text_reply("here")
    )

    result = runtime(client, context, trace_enabled=True).run_turn(SESSION_ID, "cases")

    assert result.trace is not None
    assert result.trace["tool_calls"][0]["tool"] == "search_catalog"
    assert result.trace["prompt_version"]


def test_the_trace_carries_no_prompt_text(context):
    """ADR-010: never secrets, never raw rows, never prompt text."""
    client = FakeClient(text_reply("hi"))

    result = runtime(client, context, trace_enabled=True).run_turn(SESSION_ID, "hi")

    assert "system" not in (result.trace or {})
    assert "prompt" not in str(result.trace).lower().replace("prompt_version", "")


# --------------------------------------------------------------------------
# History
# --------------------------------------------------------------------------


def test_the_buyer_message_is_recorded_before_the_model_is_called(context, sessions):
    """A turn that fails mid-way still leaves a record of what was asked."""
    client = FakeClient(LLMRateLimitError("down"))

    runtime(client, context).run_turn(SESSION_ID, "remember this")

    assert sessions.messages[0] == {
        "role": "user",
        "content": "remember this",
        "tool_payload": None,
    }


def test_the_reply_is_recorded_so_the_next_turn_can_see_it(context, sessions):
    client = FakeClient(text_reply("noted"))

    runtime(client, context).run_turn(SESSION_ID, "hello")

    assert [m["role"] for m in sessions.messages] == ["user", "assistant"]
    assert sessions.messages[-1]["content"] == "noted"


@pytest.fixture
def client_free_context(context):
    return context, None
