"""M4's exit condition: natural language to validated structured intent.

Every test here runs offline. The model is a `FakeClient` replaying a scripted
reply, which is the only way the behaviour that matters — what happens to
malformed output, to money, to a device phrase, to a budget stated one turn
after the product — can be asserted at all. A live model would make these tests
a sampling experiment.
"""

from __future__ import annotations

import json
from decimal import Decimal

import pytest

from app.llm.errors import LLMInvalidRequestError, LLMOutputError
from app.llm.extractor import IntentExtractor, merge_intent
from app.llm.models import ModelResponse, StopReason, ToolCall
from app.llm.schemas import Budget, BuyerIntent, DeviceReference, ProductRequest
from tests.llm.conftest import FakeClient, assistant, extraction_payload, say, user

CASE_FOR_IPHONE = extraction_payload(
    {
        "product_requirements": [{"product_type": "phone_case", "quantity": 1}],
        "compatibility_requirements": [{"text": "iPhone 16", "target_type": "phone_model"}],
    }
)


# --------------------------------------------------------------------------
# The happy path
# --------------------------------------------------------------------------


def test_natural_language_becomes_a_validated_intent() -> None:
    client = FakeClient(say(CASE_FOR_IPHONE))

    result = IntentExtractor(client).extract([user("I need a case for my iPhone 16")])

    assert result.intent.is_actionable
    assert [r.product_type for r in result.intent.product_requirements] == ["phone_case"]
    assert result.intent.device is not None
    assert result.intent.device.text == "iPhone 16"
    assert result.needs_clarification is False


def test_the_device_survives_as_the_buyers_words() -> None:
    """ADR-003: the model's phrase is never promoted to an identifier here.

    Whatever the model writes stays free text until `CompatibilityService`
    resolves it against `compatibility_targets`. An extractor that canonicalized
    "iPhone 16" into `iphone_16` would be guessing, and `iphone_15` is an
    equally well-formed guess with a completely wrong answer.
    """
    client = FakeClient(
        say(extraction_payload({"compatibility_requirements": [{"text": "my iphone sixteen"}]}))
    )

    result = IntentExtractor(client).extract([user("something for my iphone sixteen")])

    device = result.intent.device
    assert device is not None
    assert device.text == "my iphone sixteen"
    assert device.target_type is None
    assert not hasattr(device, "canonical_id")


def test_the_specifications_own_field_name_is_accepted_as_free_text() -> None:
    """L§5's example emits `target_identifier`, so the model may too.

    Accepting it changes nothing: a canonical-looking value gets no more
    credence than "my phone", and is re-resolved from scratch.
    """
    client = FakeClient(
        say(
            extraction_payload({"compatibility_requirements": [{"target_identifier": "iphone_16"}]})
        )
    )

    result = IntentExtractor(client).extract([user("a case for the 16")])

    device = result.intent.device
    assert device is not None
    assert device.text == "iphone_16"


def test_money_arrives_as_decimal_and_not_as_float() -> None:
    """ADR-008, and the reason extraction asks for text rather than a tool call.

    `1500.10` in the model's JSON is a `float` the moment `json.loads` sees it,
    and a `Decimal` built from a lossy float is still lossy — `Decimal(1500.10)`
    is `1500.0999999...`. `loads_decimal` parses with `parse_float=Decimal`, so
    the ceiling the buyer stated is the ceiling the ranker filters on.
    """
    client = FakeClient(say(extraction_payload({"budget": {"max": 1500.10, "currency": "INR"}})))

    result = IntentExtractor(client).extract([user("up to 1500.10")])

    # The same payload down the ordinary path, for contrast: by the time a plain
    # `json.loads` is done, the ceiling is already 1500.0999999... and no
    # later conversion can recover the 1500.10 the buyer said.
    lossy = Decimal(json.loads('{"max": 1500.10}')["max"])

    assert result.intent.budget is not None
    assert isinstance(result.intent.budget.max, Decimal)
    assert result.intent.budget.max == Decimal("1500.10")
    assert result.intent.budget.max != lossy


def test_a_fenced_code_block_is_tolerated_but_not_repaired() -> None:
    """A code fence is the commonest imperfect compliance; broken JSON is not.

    Finding the outermost braces costs nothing and saves a repair attempt.
    Anything between them is still parsed strictly.
    """
    client = FakeClient(
        say('Here you go:\n```json\n{"intent": {"preferences": {"style": "slim"}}}\n```')
    )

    result = IntentExtractor(client).extract([user("something slim")])

    assert result.intent.preferences == {"style": "slim"}


# --------------------------------------------------------------------------
# Clarification (L§7)
# --------------------------------------------------------------------------


def test_a_clarification_keeps_the_partial_intent() -> None:
    """L§7 and L§12: asking is not the same as discarding what was said.

    "I need a case" yields a real product requirement *and* a question. Throwing
    the requirement away would make the buyer repeat themselves.
    """
    client = FakeClient(
        say(
            extraction_payload(
                {"product_requirements": [{"product_type": "phone_case"}]},
                needs_clarification=True,
                clarification_question="Which phone model do you need the case for?",
            )
        )
    )

    result = IntentExtractor(client).extract([user("I need a case")])

    assert result.needs_clarification
    assert result.clarification_question == "Which phone model do you need the case for?"
    assert result.intent.is_actionable
    assert result.intent.device is None


def test_a_clarification_flag_without_a_question_is_rejected() -> None:
    """A flag with nothing to ask is a dead end, not a clarification."""
    client = FakeClient(
        say(extraction_payload({}, needs_clarification=True)),
        say(extraction_payload({}, needs_clarification=True)),
    )

    with pytest.raises(LLMOutputError, match="clarification_question"):
        IntentExtractor(client).extract([user("find me one")])


# --------------------------------------------------------------------------
# Conversation context (L§26, LLM-07)
# --------------------------------------------------------------------------


def test_a_later_turn_inherits_what_it_does_not_mention() -> None:
    """L§26's own example, which is the reason this merge exists.

    "Around 1500", following "I need a case for my iPhone 16", cannot be
    interpreted independently. The model states only the budget; the device and
    the product carry forward.
    """
    previous = BuyerIntent(
        product_requirements=[ProductRequest(product_type="phone_case")],
        compatibility_requirements=[DeviceReference(text="iPhone 16")],
    )
    client = FakeClient(say(extraction_payload({"budget": {"max": 1500}})))

    result = IntentExtractor(client).extract(
        [
            user("I need a case for my iPhone 16"),
            assistant("What's your budget?"),
            user("Around 1500"),
        ],
        previous_intent=previous,
    )

    assert result.intent.budget is not None
    assert result.intent.budget.max == Decimal(1500)
    assert result.intent.device is not None
    assert result.intent.device.text == "iPhone 16"
    assert [r.product_type for r in result.intent.product_requirements] == ["phone_case"]


def test_an_explicit_null_withdraws_a_previous_field() -> None:
    """Omission inherits, `null` removes — the distinction that makes both possible."""
    previous = BuyerIntent(budget=Budget(max=Decimal(1500)))
    client = FakeClient(say(extraction_payload({"budget": None})))

    result = IntentExtractor(client).extract(
        [user("forget the budget, show me everything")], previous_intent=previous
    )

    assert result.intent.budget is None


def test_a_change_of_mind_replaces_rather_than_accumulates() -> None:
    """ "Actually, make that a Pixel 9" is one device, not two."""
    previous = BuyerIntent(compatibility_requirements=[DeviceReference(text="iPhone 16")])
    client = FakeClient(
        say(extraction_payload({"compatibility_requirements": [{"text": "Pixel 9"}]}))
    )

    result = IntentExtractor(client).extract(
        [user("actually, make that a Pixel 9")], previous_intent=previous
    )

    assert [d.text for d in result.intent.compatibility_requirements] == ["Pixel 9"]


def test_the_previous_intent_travels_as_application_state_not_as_buyer_text() -> None:
    """L§29: the `user` channel carries buyer text and nothing else.

    Application-authored state in a user turn is indistinguishable, to the
    model, from something the buyer typed — which is the whole shape of a
    prompt-injection boundary.
    """
    previous = BuyerIntent(budget=Budget(max=Decimal(1500)))
    client = FakeClient(say(extraction_payload({})))

    IntentExtractor(client).extract([user("what about cases?")], previous_intent=previous)

    assert "1500" in client.last_system
    assert [m.content for m in client.last_messages] == ["what about cases?"]


def test_no_previous_intent_means_no_previous_intent_section() -> None:
    """L§27: do not send application data that does not exist."""
    client = FakeClient(say(extraction_payload({})))

    IntentExtractor(client).extract([user("hello")])

    assert "Previous intent" not in client.last_system


def test_history_is_trimmed_to_the_recent_window() -> None:
    """LLM-07 and L§27: older turns cost tokens the structured intent already covers."""
    conversation = [user(f"message {index}") for index in range(30)]
    client = FakeClient(say(extraction_payload({})))

    IntentExtractor(client, max_history=4).extract(conversation)

    sent = [m.content for m in client.last_messages]
    assert sent == ["message 26", "message 27", "message 28", "message 29"]


def test_trimming_never_opens_the_conversation_on_an_assistant_turn() -> None:
    """A stranded assistant turn answers a question nobody can see any more."""
    conversation = [
        user("I need a case"),
        assistant("Which phone model?"),
        user("iPhone 16"),
    ]
    client = FakeClient(say(extraction_payload({})))

    IntentExtractor(client, max_history=2).extract(conversation)

    assert [m.role for m in client.last_messages] == ["user"]
    assert client.last_messages[0].content == "iPhone 16"


# --------------------------------------------------------------------------
# Malformed output (L§46)
# --------------------------------------------------------------------------


def test_malformed_output_is_repaired_by_asking_again_once() -> None:
    """L§46 requires bounded retries; A§19 forbids repairing the output by hand."""
    client = FakeClient(say("I think you want a phone case!"), say(CASE_FOR_IPHONE))

    result = IntentExtractor(client).extract([user("case for iPhone 16")])

    assert result.intent.is_actionable
    assert client.call_count == 2
    repair = client.last_messages[-1].content
    assert "could not be used" in repair
    assert client.last_messages[-2].role == "assistant"


def test_the_repair_attempt_is_bounded() -> None:
    """ "The agent should not repeatedly retry indefinitely" — L§46."""
    client = FakeClient(*[say("not json") for _ in range(5)])

    with pytest.raises(LLMOutputError, match="no JSON object"):
        IntentExtractor(client).extract([user("hello")])

    assert client.call_count == 2


def test_repairs_can_be_switched_off_entirely() -> None:
    client = FakeClient(say("not json"))

    with pytest.raises(LLMOutputError):
        IntentExtractor(client, max_repair_attempts=0).extract([user("hello")])

    assert client.call_count == 1


def test_an_envelope_without_an_intent_is_reported_not_assumed() -> None:
    """A bare intent object is a plausible mistake and still not accepted.

    Accepting it would be exactly the helpful coercion A§19 forbids: the shape
    the caller asked for is the shape it validates.
    """
    bare = {"product_requirements": [{"product_type": "phone_case"}]}
    client = FakeClient(say(bare), say(bare))

    with pytest.raises(LLMOutputError, match="no 'intent' object"):
        IntentExtractor(client).extract([user("a case")])


def test_a_truncated_answer_is_never_treated_as_a_complete_one(
    truncated: ModelResponse,
) -> None:
    """And it is not retried: the same request truncates the same way."""
    client = FakeClient(truncated)

    with pytest.raises(LLMOutputError, match="truncated"):
        IntentExtractor(client).extract([user("a case for my iPhone 16")])

    assert client.call_count == 1


def test_a_refusal_is_a_failure_and_not_an_empty_intent() -> None:
    client = FakeClient(ModelResponse(text="", stop_reason=StopReason.REFUSAL))

    with pytest.raises(LLMOutputError, match="declined"):
        IntentExtractor(client).extract([user("something")])


def test_a_tool_call_during_extraction_is_a_failure() -> None:
    """No tools are offered on this call, so one coming back means the payload lied."""
    client = FakeClient(
        ModelResponse(
            text="",
            tool_calls=(ToolCall(id="1", name="search_catalog"),),
            stop_reason=StopReason.TOOL_USE,
        )
    )

    with pytest.raises(LLMOutputError, match="tool"):
        IntentExtractor(client).extract([user("find me a case")])


def test_extraction_offers_no_tools_at_all() -> None:
    client = FakeClient(say(extraction_payload({})))

    IntentExtractor(client).extract([user("hello")])

    assert client.last["tools"] is None
    assert client.last["temperature"] == 0.0


# --------------------------------------------------------------------------
# No catalog facts (LLM-03's last requirement)
# --------------------------------------------------------------------------


def test_an_intent_cannot_carry_a_catalog_fact() -> None:
    """RULE 1, RULE 2, RULE 6: the model contributes requirements, never facts.

    The schema has no field for a SKU, a price of a product or a stock level,
    and `extra="forbid"` means inventing one fails validation rather than being
    silently dropped — which is the difference between a caught hallucination
    and a fabricated recommendation.
    """
    fabricated = extraction_payload(
        {
            "product_requirements": [{"product_type": "phone_case"}],
            "sku": "CC-CASE-001",
            "price": "999.00",
            "in_stock": True,
        }
    )
    client = FakeClient(say(fabricated), say(fabricated))

    with pytest.raises(LLMOutputError, match="Extra inputs are not permitted"):
        IntentExtractor(client).extract([user("a case for my iPhone 16")])


def test_a_model_supplied_weight_is_refused() -> None:
    """R§11 and ADR-004: the model may name a profile, never state a weight."""
    weighted = extraction_payload({"weights": {"price": 0.9}})
    client = FakeClient(say(weighted), say(weighted))

    with pytest.raises(LLMOutputError, match="Extra inputs"):
        IntentExtractor(client).extract([user("cheapest one")])


def test_a_profile_may_be_named() -> None:
    client = FakeClient(say(extraction_payload({"weight_profile": "price_sensitive"})))

    result = IntentExtractor(client).extract([user("the cheapest one that fits")])

    assert result.intent.weight_profile == "price_sensitive"


# --------------------------------------------------------------------------
# Caller errors
# --------------------------------------------------------------------------


def test_an_empty_conversation_is_a_caller_error() -> None:
    with pytest.raises(LLMInvalidRequestError, match="at least one message"):
        IntentExtractor(FakeClient()).extract([])


def test_extracting_from_the_agents_own_turn_is_a_caller_error() -> None:
    """Otherwise the agent's question gets re-extracted as the buyer's request."""
    with pytest.raises(LLMInvalidRequestError, match="buyer's message last"):
        IntentExtractor(FakeClient()).extract([user("hi"), assistant("Which model?")])


@pytest.mark.parametrize(
    ("kwargs", "match"),
    [
        ({"max_history": 0}, "max_history"),
        ({"max_repair_attempts": -1}, "max_repair_attempts"),
    ],
)
def test_a_nonsensical_configuration_fails_at_construction(
    kwargs: dict[str, int], match: str
) -> None:
    with pytest.raises(ValueError, match=match):
        IntentExtractor(FakeClient(), **kwargs)


def test_the_extractor_reports_its_prompt_version() -> None:
    """L§28: a stored trace is evidence about the prompt that produced it."""
    assert IntentExtractor(FakeClient()).prompt_version == "1.0.0"


# --------------------------------------------------------------------------
# merge_intent on its own
# --------------------------------------------------------------------------


def test_merge_without_a_previous_intent_returns_the_update() -> None:
    update = BuyerIntent(budget=Budget(max=Decimal(500)))

    assert merge_intent(None, update, {"budget"}) is update


def test_merge_covers_every_field_of_the_intent() -> None:
    """A field added later must not silently stop carrying forward.

    The merge iterates `model_fields` rather than a hand-written list precisely
    so that this holds; the test is what stops the list from creeping back in.
    """
    previous = BuyerIntent(
        product_requirements=[ProductRequest(product_type="charger")],
        compatibility_requirements=[DeviceReference(text="MacBook Air")],
        budget=Budget(max=Decimal(3000)),
        preferences={"size": "compact"},
        weight_profile="premium",
    )

    carried = merge_intent(previous, BuyerIntent(), stated=())

    assert carried == previous
