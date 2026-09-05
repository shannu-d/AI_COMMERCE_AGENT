"""What the model may ask for, and what its arguments must survive (LLM-05, LLM-06).

A tool schema is a security boundary written as a type. Most of what follows is
therefore not testing behaviour but testing *absence*: that no tool takes a
price, that `create_order` does not exist, that `request_approval` has no field
capable of expressing approval, and that a surplus argument is refused rather
than dropped.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest

from app.llm.errors import LLMOutputError
from app.llm.tool_schemas import (
    EXPOSED_TOOL_NAMES,
    FORBIDDEN_TOOL_NAMES,
    MAX_STATED_AMOUNT,
    READ_ONLY_TOOL_NAMES,
    TOOL_SCHEMAS,
    RiskTier,
    build_tool_definitions,
    validate_tool_arguments,
)

CATEGORY_SLUGS = ("phone_case", "charger", "cable", "earbuds")


# --------------------------------------------------------------------------
# The registry, as a whole
# --------------------------------------------------------------------------


def test_the_registry_is_exactly_the_specifications_tools_minus_create_order() -> None:
    """A§17 lists nine; A§15 says one of them must not be freely available.

    ADR-009 resolves the contradiction in favour of A§15, which is the
    safety-bearing statement — so `create_order` is not a tool at all.
    """
    assert set(EXPOSED_TOOL_NAMES) == {
        "search_catalog",
        "get_product",
        "get_compatible_products",
        "check_inventory",
        "get_upsell_candidates",
        "propose_cart",
        "request_approval",
        "get_order_status",
    }


def test_create_order_is_not_registered_at_all() -> None:
    """Not registered-and-failing. A registered tool is one the model can reason about.

    ADR-009: order creation is a user-initiated API path behind the Policy
    Engine, and the safest tool is the one that does not exist.
    """
    assert "create_order" in FORBIDDEN_TOOL_NAMES
    assert "create_order" not in TOOL_SCHEMAS
    assert not any("order" in name and "status" not in name for name in EXPOSED_TOOL_NAMES)


def test_a_forbidden_tool_call_is_reported_as_forbidden_not_as_unknown() -> None:
    """So the attempt shows up in logs instead of blending into typos."""
    with pytest.raises(LLMOutputError, match="not available to the model"):
        validate_tool_arguments("create_order", {})


def test_the_read_only_subset_is_a_subset() -> None:
    """M5 exposes these before the cart and order milestones arrive."""
    assert set(READ_ONLY_TOOL_NAMES) <= set(EXPOSED_TOOL_NAMES)
    assert "propose_cart" not in READ_ONLY_TOOL_NAMES
    assert "request_approval" not in READ_ONLY_TOOL_NAMES


def test_the_tools_that_change_state_are_graded_higher() -> None:
    """A§23: the tier is what the executor checks before running a tool."""
    assert TOOL_SCHEMAS["propose_cart"].tier is RiskTier.MEDIUM
    assert TOOL_SCHEMAS["request_approval"].tier is RiskTier.MEDIUM
    assert all(TOOL_SCHEMAS[name].tier is RiskTier.LOW for name in READ_ONLY_TOOL_NAMES)


@pytest.mark.parametrize("name", EXPOSED_TOOL_NAMES)
def test_no_tool_accepts_a_catalog_fact(name: str) -> None:
    """A§13, RULE 6, ADR-009: the backend reads price and stock; the model states neither.

    `max_price` is deliberately not in this list — it is the buyer's ceiling, a
    constraint the buyer stated, and never a claim about what something costs.
    """
    forbidden = {
        "price",
        "unit_price",
        "total",
        "subtotal",
        "amount",
        "stock",
        "stock_quantity",
        "in_stock",
        "available",
        "discount",
        "compatible",
        "is_compatible",
    }
    properties = set(TOOL_SCHEMAS[name].json_schema().get("properties", {}))

    assert not (properties & forbidden), f"{name} accepts {sorted(properties & forbidden)}"


def test_propose_cart_carries_variants_and_quantities_and_nothing_else() -> None:
    """The total the buyer approves must be one the application computed."""
    schema = TOOL_SCHEMAS["propose_cart"].json_schema()
    item = schema["$defs"]["CartItemArg"]

    assert set(schema["properties"]) == {"items"}
    assert set(item["properties"]) == {"variant_id", "quantity"}


def test_request_approval_has_no_field_that_could_express_approval() -> None:
    """ADR-007: approval is an act the buyer performs, not a conclusion the model reaches."""
    properties = set(TOOL_SCHEMAS["request_approval"].json_schema()["properties"])

    assert properties == {"cart_id"}
    assert not properties & {"approved", "status", "confirm", "confirmed", "authorized"}


@pytest.mark.parametrize("name", EXPOSED_TOOL_NAMES)
def test_every_tool_tells_the_model_where_facts_come_from(name: str) -> None:
    """A description is the model's only documentation, so it carries the grounding rule."""
    definition = TOOL_SCHEMAS[name]

    assert len(definition.description) > 80
    assert definition.milestone.startswith("M")


# --------------------------------------------------------------------------
# The payload sent to the model
# --------------------------------------------------------------------------


def test_categories_are_enumerated_from_the_merchants_own_slugs() -> None:
    """ADR-009, open question B2: the model cannot name a category that does not exist.

    Built from the database at registry time, so it cannot drift from the
    catalog the way a hard-coded list would.
    """
    payload = build_tool_definitions(category_slugs=CATEGORY_SLUGS, names=["search_catalog"])
    category = payload[0]["input_schema"]["properties"]["category"]

    assert category["enum"] == [*CATEGORY_SLUGS, None]
    assert "anyOf" not in category


def test_without_slugs_the_category_is_left_unconstrained() -> None:
    """An empty enum would offer the model no valid category at all."""
    payload = build_tool_definitions(names=["search_catalog"])

    assert "enum" not in payload[0]["input_schema"]["properties"]["category"]


def test_a_tool_without_a_category_is_untouched_by_the_injection() -> None:
    payload = build_tool_definitions(category_slugs=CATEGORY_SLUGS, names=["check_inventory"])

    assert "category" not in payload[0]["input_schema"]["properties"]


def test_the_search_schema_distinguishes_a_requirement_from_a_wish() -> None:
    """The structural half of the 1.3.0 fix.

    A live turn answered "find noise-cancelling earbuds" with three products
    that have no ANC, because the requirement went into `search_query`. It went
    there because `attributes` reached the model as a bare object titled
    "Attributes", with nothing saying it is the field that eliminates. Both
    descriptions now say which is which, and this asserts they do — the prompt
    carries the same rule, but the prompt is not a control (L§29, ADR-009).
    """
    properties = build_tool_definitions(names=["search_catalog"])[0]["input_schema"]["properties"]

    attributes = properties["attributes"]["description"]
    assert "REQUIREMENT" in attributes
    assert "eliminate" in attributes
    # The three predicate forms `app.attributes` implements, and no others.
    assert "minimum_<name>" in attributes
    assert "maximum_<name>" in attributes

    query = properties["search_query"]["description"]
    assert "RELEVANCE" in query
    assert "never" in query and "removes" in query


def test_attribute_names_are_enumerated_from_the_merchants_own_rows() -> None:
    """The same argument as the category enum (ADR-009, B2), one level down.

    A guessed attribute name does not fail loudly: a missing attribute always
    fails, so `noise_cancelling` where the catalogue records `anc` eliminates
    every product and returns nothing. Listing the real names is what makes the
    model's choice informed rather than lucky.
    """
    vocabulary = {"earbuds": ("anc", "battery_hours"), "charger": ("wattage",)}
    payload = build_tool_definitions(
        category_slugs=CATEGORY_SLUGS,
        attribute_vocabulary=vocabulary,
        names=["search_catalog"],
    )
    description = payload[0]["input_schema"]["properties"]["attributes"]["description"]

    assert "earbuds: anc, battery_hours" in description
    assert "charger: wattage" in description


def test_without_a_vocabulary_the_attributes_description_still_stands_alone() -> None:
    """The instruction is not conditional on the injection.

    A merchant with no attributes recorded anywhere would otherwise leave the
    field undocumented again, which is the exact state that caused the failure.
    """
    payload = build_tool_definitions(names=["search_catalog"])
    description = payload[0]["input_schema"]["properties"]["attributes"]["description"]

    assert "REQUIREMENT" in description
    assert "Attribute names by category" not in description


def test_the_currency_is_enumerated_rather_than_left_open() -> None:
    """Found by the same live probe as the 1.3.0 fix, one field over.

    `currency` reached the model as a bare optional string, and the model filled
    it in unasked: a live call to `search_catalog` carried `"USD"`, which
    `_supported` then refused — failing an otherwise correct search on a value
    the buyer never mentioned. ADR-008 is explicit that a currency mismatch is
    an error rather than something to convert, so the right fix is to make the
    wrong value unavailable, not merely rejected.

    Unconditional, unlike the category enum: this is an application constant,
    not merchant data. The enum informs the model; the validator still decides,
    which `test_an_unsupported_currency_is_refused` asserts separately — a
    schema constraint the provider chose not to honour must not become the only
    thing between a wrong currency and a query.
    """
    from app.llm.schemas import SUPPORTED_CURRENCIES

    for name in ("search_catalog", "get_compatible_products"):
        currency = build_tool_definitions(names=[name])[0]["input_schema"]["properties"]["currency"]

        assert currency["enum"] == [*sorted(SUPPORTED_CURRENCIES), None]
        assert "anyOf" not in currency


def test_a_tool_without_attributes_is_untouched_by_the_vocabulary() -> None:
    payload = build_tool_definitions(
        attribute_vocabulary={"earbuds": ("anc",)}, names=["check_inventory"]
    )

    assert "attributes" not in payload[0]["input_schema"]["properties"]


def test_the_payload_is_stable_between_runs() -> None:
    """A byte-stable payload is a cacheable one, and a diffable one."""
    first = build_tool_definitions(category_slugs=CATEGORY_SLUGS)
    second = build_tool_definitions(category_slugs=CATEGORY_SLUGS)

    assert first == second
    assert [tool["name"] for tool in first] == sorted(tool["name"] for tool in first)


def test_a_subset_can_be_selected_and_a_typo_cannot() -> None:
    """M5 exposes the read-only tools; a misspelling must not silently offer nothing."""
    assert len(build_tool_definitions(names=READ_ONLY_TOOL_NAMES)) == len(READ_ONLY_TOOL_NAMES)

    with pytest.raises(KeyError, match="search_catalogue"):
        build_tool_definitions(names=["search_catalogue"])


def test_every_tool_renders_a_schema_the_api_will_accept() -> None:
    for tool in build_tool_definitions(category_slugs=CATEGORY_SLUGS):
        assert set(tool) == {"name", "description", "input_schema"}
        assert tool["input_schema"]["type"] == "object"
        assert "title" not in tool["input_schema"]


# --------------------------------------------------------------------------
# Argument validation (A§19, stage two)
# --------------------------------------------------------------------------


def test_valid_arguments_come_back_typed() -> None:
    arguments = validate_tool_arguments(
        "search_catalog", {"category": "phone_case", "max_price": 1500, "currency": "INR"}
    )

    assert arguments.category == "phone_case"  # type: ignore[attr-defined]
    assert arguments.max_price == Decimal(1500)  # type: ignore[attr-defined]


def test_a_model_supplied_amount_survives_as_an_exact_decimal() -> None:
    """Tool arguments arrive already JSON-decoded, so this is the only interception point.

    `Decimal(str(1500.5))` is exact — `str` on a float gives the shortest
    round-tripping representation. What ADR-008 forbids is float *arithmetic*
    and float *storage*, not one bounded conversion at an input boundary.
    """
    arguments = validate_tool_arguments("search_catalog", {"max_price": 1500.5})

    assert arguments.max_price == Decimal("1500.5")  # type: ignore[attr-defined]


def test_an_absurd_amount_fails_here_rather_than_at_the_database() -> None:
    """A hallucinated `1e30` should not travel as far as `NUMERIC(12,2)`."""
    with pytest.raises(LLMOutputError, match="max_price"):
        validate_tool_arguments("search_catalog", {"max_price": float(MAX_STATED_AMOUNT) * 10})


def test_an_unknown_tool_is_refused() -> None:
    with pytest.raises(LLMOutputError, match="unknown tool"):
        validate_tool_arguments("delete_everything", {})


def test_a_surplus_argument_is_refused_rather_than_dropped() -> None:
    """A§19: reject before execution. A dropped argument is a hallucination nobody saw."""
    with pytest.raises(LLMOutputError, match="Extra inputs are not permitted"):
        validate_tool_arguments("check_inventory", {"sku": "CC-CASE-001", "price": "1.00"})


def test_the_rejection_names_what_was_wrong() -> None:
    """The runtime has to be able to tell the model what to fix."""
    with pytest.raises(LLMOutputError) as caught:
        validate_tool_arguments("check_inventory", {"sku": "CC-1", "quantity": 500})

    assert "quantity" in str(caught.value)


@pytest.mark.parametrize("name", ["get_product", "check_inventory"])
def test_exactly_one_lookup_key_is_required(name: str) -> None:
    """A§30/ADR-009: an id and a SKU are lookup keys, and two of them is ambiguity."""
    key = "product_id" if name == "get_product" else "variant_id"

    validate_tool_arguments(name, {key: "some-id"})
    validate_tool_arguments(name, {"sku": "CC-CASE-001"})

    with pytest.raises(LLMOutputError, match="exactly one"):
        validate_tool_arguments(name, {})
    with pytest.raises(LLMOutputError, match="exactly one"):
        validate_tool_arguments(name, {key: "some-id", "sku": "CC-CASE-001"})


def test_a_quantity_outside_the_bounds_is_refused() -> None:
    """A§18/ADR-009: `1 <= quantity <= 99`."""
    with pytest.raises(LLMOutputError):
        validate_tool_arguments("propose_cart", {"items": [{"variant_id": "v", "quantity": 0}]})
    with pytest.raises(LLMOutputError):
        validate_tool_arguments("propose_cart", {"items": [{"variant_id": "v", "quantity": 100}]})


def test_an_empty_cart_proposal_is_refused() -> None:
    with pytest.raises(LLMOutputError):
        validate_tool_arguments("propose_cart", {"items": []})


def test_an_unsupported_currency_is_refused() -> None:
    """A§18: "currency is valid"."""
    with pytest.raises(LLMOutputError, match="currency"):
        validate_tool_arguments("search_catalog", {"currency": "USD"})


def test_a_device_reaches_the_tool_as_the_buyers_phrase() -> None:
    """ADR-003 again: resolution happens in the application, never in the schema."""
    arguments = validate_tool_arguments("get_compatible_products", {"device": "my iPhone 16"})

    assert arguments.device == "my iPhone 16"  # type: ignore[attr-defined]


@pytest.mark.parametrize("value", [{}, {"device": ""}])
def test_a_missing_device_is_refused(value: dict[str, Any]) -> None:
    with pytest.raises(LLMOutputError):
        validate_tool_arguments("get_compatible_products", value)
