"""The structured buyer intent (L§5, LLM-02).

The schema is the last place a hallucination can be caught cheaply. Everything
downstream — the ranker, the services, the policy engine — assumes an intent has
already been validated, so what these tests protect is the assumption itself:
that money is exact, that a device is a phrase, that a field nobody defined
cannot ride along, and that an intent carries no catalog fact at all.
"""

from __future__ import annotations

import json
from decimal import Decimal
from typing import Any

import pytest
from pydantic import ValidationError

from app.llm.errors import LLMOutputError
from app.llm.schemas import (
    MAX_QUANTITY,
    SUPPORTED_CURRENCIES,
    Budget,
    BuyerIntent,
    DeviceReference,
    IntentExtraction,
    ProductRequest,
    loads_decimal,
)

# --------------------------------------------------------------------------
# loads_decimal (ADR-008)
# --------------------------------------------------------------------------


def test_a_json_number_becomes_a_decimal_not_a_float() -> None:
    """The single reason this function exists.

    `json.loads('{"max": 1500.10}')` produces a float that has already lost
    precision; no validator downstream can restore it.
    """
    parsed = loads_decimal('{"max": 1500.10}')

    assert parsed["max"] == Decimal("1500.10")
    assert isinstance(parsed["max"], Decimal)


def test_an_integer_stays_an_integer() -> None:
    """Integers are exact in both representations; only floats are the problem."""
    assert loads_decimal('{"quantity": 2}')["quantity"] == 2
    assert isinstance(loads_decimal('{"quantity": 2}')["quantity"], int)


def test_invalid_json_is_a_model_output_error() -> None:
    """Not a `JSONDecodeError`: callers of this layer catch `LLMError`."""
    with pytest.raises(LLMOutputError, match="not valid JSON"):
        loads_decimal("{oops")


# --------------------------------------------------------------------------
# Budget
# --------------------------------------------------------------------------


def test_a_float_budget_is_refused_rather_than_coerced() -> None:
    """A float here means `loads_decimal` was bypassed somewhere upstream.

    Coercing it would hide the bypass and leave the buyer with a ceiling that is
    quietly wrong, which is the failure ADR-008 exists to prevent.
    """
    with pytest.raises(ValidationError, match="must not arrive as a float"):
        Budget(max=1500.10)  # type: ignore[arg-type]


@pytest.mark.parametrize("value", ["1500.50", 1500, Decimal("1500.50")])
def test_a_budget_accepts_exact_representations(value: Any) -> None:
    assert Budget(max=value).max == Decimal(str(value))


def test_a_budget_must_be_positive() -> None:
    """A ceiling of zero is not a cheap buyer, it is a broken extraction."""
    with pytest.raises(ValidationError):
        Budget(max=Decimal(0))


def test_an_unsupported_currency_is_refused() -> None:
    """ADR-008 defines no conversion anywhere, so an unpriceable currency stops here."""
    with pytest.raises(ValidationError, match="unsupported currency"):
        Budget(max=Decimal(1500), currency="USD")


def test_a_currency_is_normalized_to_upper_case() -> None:
    assert Budget(max=Decimal(1500), currency="inr").currency == "INR"
    assert SUPPORTED_CURRENCIES == frozenset({"INR"})


# --------------------------------------------------------------------------
# ProductRequest
# --------------------------------------------------------------------------


def test_quantity_is_bounded() -> None:
    """A§18/ADR-009: a four-digit quantity from a chat message is never a purchase."""
    assert ProductRequest(product_type="phone_case", quantity=MAX_QUANTITY).quantity == 99
    with pytest.raises(ValidationError):
        ProductRequest(product_type="phone_case", quantity=MAX_QUANTITY + 1)
    with pytest.raises(ValidationError):
        ProductRequest(product_type="phone_case", quantity=0)


def test_requirements_and_preferences_are_separate_fields() -> None:
    """ADR-005: one eliminates, the other only reorders.

    Collapsing them into L§5's single `preferences` object would make the
    difference between "must be USB-C" and "prefers USB-C" a matter of
    inference at ranking time, which is where it cannot be recovered.
    """
    request = ProductRequest(
        product_type="charger",
        required_attributes={"port_type": "usb_c"},
        preferences={"colour": "black"},
    )

    assert request.required_attributes == {"port_type": "usb_c"}
    assert request.preferences == {"colour": "black"}


def test_a_float_item_ceiling_is_refused_too() -> None:
    with pytest.raises(ValidationError, match="must not arrive as a float"):
        ProductRequest(product_type="charger", max_price=999.99)  # type: ignore[arg-type]


# --------------------------------------------------------------------------
# DeviceReference (ADR-003)
# --------------------------------------------------------------------------


def test_a_device_is_stored_verbatim() -> None:
    """The phrase is a lookup key for `compatibility_targets`, not an identifier."""
    assert DeviceReference(text="iPhone 16").text == "iPhone 16"
    assert DeviceReference(text="my MacBook").target_type is None


def test_the_specifications_target_identifier_is_read_as_text() -> None:
    """L§5's example emits it, so it is accepted — and demoted to free text."""
    device = DeviceReference.model_validate({"target_identifier": "iphone_16"})

    assert device.text == "iphone_16"


def test_supplying_both_names_is_refused_rather_than_resolved() -> None:
    """Two device phrases in one reference is ambiguity, and ambiguity is asked about.

    The alias only fills in for a missing `text`. When both arrive they may
    disagree — "iPhone 16" and `iphone_15` here — and picking one would be a
    coin flip over which phone the buyer owns.
    """
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        DeviceReference.model_validate({"text": "iPhone 16", "target_identifier": "iphone_15"})


def test_an_unknown_target_type_is_refused() -> None:
    """The three types are `compatibility_targets.target_type`'s own vocabulary."""
    with pytest.raises(ValidationError):
        DeviceReference(text="iPhone 16", target_type="phone")  # type: ignore[arg-type]


def test_an_empty_device_phrase_is_refused() -> None:
    with pytest.raises(ValidationError):
        DeviceReference(text="")


# --------------------------------------------------------------------------
# BuyerIntent
# --------------------------------------------------------------------------


def test_an_intent_without_a_product_is_not_actionable() -> None:
    """L§6: without a product type there is nothing to search *for*."""
    assert not BuyerIntent().is_actionable
    assert not BuyerIntent(budget=Budget(max=Decimal(1500))).is_actionable
    assert BuyerIntent(
        product_requirements=[ProductRequest(product_type="phone_case")]
    ).is_actionable


def test_the_first_stated_device_is_the_one_reported() -> None:
    intent = BuyerIntent(
        compatibility_requirements=[
            DeviceReference(text="iPhone 16"),
            DeviceReference(text="Pixel 9"),
        ]
    )

    assert intent.device is not None
    assert intent.device.text == "iPhone 16"
    assert BuyerIntent().device is None


@pytest.mark.parametrize(
    "fabricated",
    [
        {"sku": "CC-CASE-001"},
        {"price": "999.00"},
        {"in_stock": True},
        {"products": [{"name": "AeroCase Pro"}]},
        {"weights": {"price": 0.9}},
    ],
)
def test_an_intent_cannot_carry_a_catalog_fact_or_a_weight(fabricated: dict[str, Any]) -> None:
    """RULE 1, RULE 2, RULE 6, R§11.

    `extra="forbid"` is what turns a hallucinated field into a caught error
    rather than a silently dropped one. The distinction matters: a dropped SKU
    is a hallucination nobody noticed.
    """
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        BuyerIntent.model_validate(fabricated)


def test_a_weight_profile_may_be_named() -> None:
    """ADR-004: the model may select a profile by name. It may not emit weights."""
    assert BuyerIntent(weight_profile="price_sensitive").weight_profile == "price_sensitive"


# --------------------------------------------------------------------------
# IntentExtraction
# --------------------------------------------------------------------------


def test_a_clarification_requires_a_question() -> None:
    with pytest.raises(ValidationError, match="no clarification_question"):
        IntentExtraction(intent=BuyerIntent(), needs_clarification=True)


def test_an_intent_and_a_question_coexist() -> None:
    """L§7 with L§12: asking does not throw away what the buyer already said."""
    extraction = IntentExtraction(
        intent=BuyerIntent(product_requirements=[ProductRequest(product_type="phone_case")]),
        needs_clarification=True,
        clarification_question="Which phone model?",
    )

    assert extraction.intent.is_actionable
    assert extraction.needs_clarification


def test_the_whole_envelope_round_trips_from_model_json() -> None:
    """The shape the extraction prompt asks for, validated end to end."""
    payload = loads_decimal(
        json.dumps(
            {
                "intent": {
                    "product_requirements": [
                        {
                            "product_type": "phone_case",
                            "quantity": 2,
                            "required_attributes": {"material": "silicone"},
                            "preferences": {"style": "slim"},
                            "max_price": 1200,
                        }
                    ],
                    "compatibility_requirements": [
                        {"text": "iPhone 16", "target_type": "phone_model"}
                    ],
                    "budget": {"max": 2500, "currency": "INR"},
                    "preferences": {"colour": "black"},
                    "weight_profile": None,
                },
                "needs_clarification": False,
                "clarification_question": None,
            }
        )
    )

    extraction = IntentExtraction.model_validate(payload)

    request = extraction.intent.product_requirements[0]
    assert request.quantity == 2
    assert request.max_price == Decimal(1200)
    assert extraction.intent.budget is not None
    assert extraction.intent.budget.max == Decimal(2500)
