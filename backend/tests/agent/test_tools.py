"""Tool handlers: what they ground, and what they refuse to invent (ADR-009).

The tools are where a model-supplied string becomes a database lookup, and every
test here is about that conversion being one-way. A SKU the model made up does
not become a product; a device phrase that does not resolve does not become a
guess; a price never enters through an argument at all.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest

from app.agent.errors import ToolError, ToolErrorCode
from app.agent.tools.catalog import get_product, search_catalog
from app.agent.tools.compatibility import get_compatible_products
from app.agent.tools.inventory import check_inventory, get_upsell_candidates
from app.domain.catalog import ProductDetail, ProductSummary
from app.domain.compatibility import CompatibilityTargetView, ResolvedTarget
from app.domain.inventory import StockStatus, StockView
from app.domain.ranking import RecommendationOutcome
from app.llm.tool_schemas import (
    CheckInventoryArgs,
    GetCompatibleProductsArgs,
    GetProductArgs,
    GetUpsellCandidatesArgs,
    SearchCatalogArgs,
)
from tests.agent.conftest import make_ranked, make_recommendation, make_variant

IPHONE_16 = ResolvedTarget(
    canonical_identifier="iphone_16",
    target_type="phone_model",
    display_name="iPhone 16",
    requested_text="iPhone 16",
    normalized_text="iphone_16",
)


# --------------------------------------------------------------------------
# search_catalog (T1)
# --------------------------------------------------------------------------


def test_search_returns_what_the_ranker_placed(context, memory, recommendations):
    """R§11, A§52: the runtime does not ask the model to inspect products.

    The ordering, the reasons and the scores all come from `RecommendationService`.
    The model's influence stopped at the arguments.
    """
    variant = make_variant(sku="CASE-IP16-BLK", price="999.00")
    recommendations.result = make_recommendation(make_ranked(variant))

    result = search_catalog(context, memory, SearchCatalogArgs(category="phone_case"))

    assert result["outcome"] == "EXACT_MATCH"
    assert [row["sku"] for row in result["results"]] == ["CASE-IP16-BLK"]
    assert result["results"][0]["reason"] == "Best overall"
    assert result["results"][0]["price"] == "999.00"


def test_search_keeps_the_ranked_result_for_the_response(context, memory, recommendations):
    """ADR-010: `recommendations[]` is built from this, not from model prose."""
    recommendations.result = make_recommendation(make_ranked(make_variant()))

    search_catalog(context, memory, SearchCatalogArgs(category="phone_case"))

    assert "phone_case" in memory.recommendations


def test_search_rejects_a_category_the_merchant_does_not_sell(context, memory):
    """ADR-009, closing B2. The schema enumerates real slugs; this is the second
    check, for a model that ignores the schema."""
    with pytest.raises(ToolError) as error:
        search_catalog(context, memory, SearchCatalogArgs(category="hats"))

    assert error.value.code is ToolErrorCode.CATEGORY_NOT_FOUND


def test_a_stated_budget_reaches_the_ranker_as_a_decimal(context, memory, recommendations):
    """ADR-008. A budget that became a float on the way in would be a different
    ceiling from the one the buyer stated."""
    recommendations.result = make_recommendation(make_ranked(make_variant()))

    search_catalog(context, memory, SearchCatalogArgs(max_price=Decimal("1500.10")))

    requirement = recommendations.requirements[-1]
    assert requirement.max_price == Decimal("1500.10")
    assert isinstance(requirement.max_price, Decimal)


def test_a_no_match_carries_alternatives_in_their_own_field(context, memory, recommendations):
    """R§14: an alternative is never presented as a match."""
    recommendations.result = make_recommendation(
        outcome=RecommendationOutcome.NO_MATCH_WITH_ALTERNATIVES
    )

    result = search_catalog(context, memory, SearchCatalogArgs(category="phone_case"))

    assert result["outcome"] == "NO_MATCH_WITH_ALTERNATIVES"
    assert result["results"] == []
    assert "alternatives" in result


# --------------------------------------------------------------------------
# get_product (T2)
# --------------------------------------------------------------------------


def test_a_fabricated_sku_is_rejected_and_touches_no_service(context, memory, catalog):
    """ADR-009's named M5 test: a fabricated SKU yields VARIANT_NOT_FOUND.

    And nothing else runs. The lookup fails and the handler returns; there is no
    path from an invented identifier to a product description.
    """
    with pytest.raises(ToolError) as error:
        get_product(context, memory, GetProductArgs(sku="TOTALLY-MADE-UP"))

    assert error.value.code is ToolErrorCode.VARIANT_NOT_FOUND
    assert catalog.calls == ["get_variant_by_sku:TOTALLY-MADE-UP"]


def test_a_malformed_product_id_reads_as_not_found(context, memory):
    """The buyer cannot tell "that is not a UUID" from "no such product", and
    telling the model the difference teaches it about the id format."""
    with pytest.raises(ToolError) as error:
        get_product(context, memory, GetProductArgs(product_id="not-a-uuid"))

    assert error.value.code is ToolErrorCode.PRODUCT_NOT_FOUND


def test_get_product_returns_every_variant_with_its_own_price(context, memory, catalog, inventory):
    """ADR-002: the variant is the sellable unit, so the price lives there."""
    black = make_variant(sku="CASE-BLK", name="Black", price="999.00")
    blue = make_variant(sku="CASE-BLU", name="Blue", price="1099.00")
    product_id = black.product_id
    catalog.products[product_id] = ProductDetail(
        product=ProductSummary(
            id=product_id,
            slug="aerocase-pro",
            name="AeroCase Pro",
            category_slug="phone_case",
        ),
        variants=(black, blue),
    )
    inventory.stock[black.id] = StockView(
        variant_id=black.id, quantity=7, reserved_quantity=0, status=StockStatus.IN_STOCK
    )

    result = get_product(context, memory, GetProductArgs(product_id=str(product_id)))

    assert {v["sku"]: v["price"] for v in result["variants"]} == {
        "CASE-BLK": "999.00",
        "CASE-BLU": "1099.00",
    }
    assert result["variants"][0]["stock_status"] == "IN_STOCK"


def test_no_variant_payload_carries_an_exact_quantity(context, memory, catalog, inventory):
    """ADR-009, closing E5. A merchant's stock position is not buyer-facing."""
    variant = make_variant()
    catalog.products[variant.product_id] = ProductDetail(
        product=ProductSummary(
            id=variant.product_id, slug="p", name="P", category_slug="phone_case"
        ),
        variants=(variant,),
    )
    inventory.stock[variant.id] = StockView(
        variant_id=variant.id, quantity=42, reserved_quantity=0, status=StockStatus.IN_STOCK
    )

    result = get_product(context, memory, GetProductArgs(product_id=str(variant.product_id)))

    assert "42" not in str(result)
    assert "quantity" not in result["variants"][0]


# --------------------------------------------------------------------------
# get_compatible_products (T3, ADR-003)
# --------------------------------------------------------------------------


def test_an_unresolvable_device_is_a_question_not_a_no_match(
    context, memory, compatibility, recommendations
):
    """ADR-003. The two look identical from outside and mean opposite things.

    A no-match says the catalog has nothing; an unresolved device says nobody
    knows what was asked for. Collapsing them tells a buyer their phone is
    unsupported when the truth is that the phrase was unclear.
    """
    with pytest.raises(ToolError) as error:
        get_compatible_products(context, memory, GetCompatibleProductsArgs(device="my new phone"))

    assert error.value.code is ToolErrorCode.DEVICE_NOT_RESOLVED
    assert recommendations.requirements == []


def test_an_ambiguous_device_offers_the_real_candidates(context, memory, compatibility):
    """ADR-003 requires a clarification rather than a coin flip, and a
    clarification is more useful when it names the options."""
    compatibility.ambiguous["iPhone"] = (
        CompatibilityTargetView(
            id=uuid.uuid4(),
            target_type="phone_model",
            canonical_identifier="iphone_15",
            display_name="iPhone 15",
            aliases=(),
        ),
        CompatibilityTargetView(
            id=uuid.uuid4(),
            target_type="phone_model",
            canonical_identifier="iphone_16",
            display_name="iPhone 16",
            aliases=(),
        ),
    )

    with pytest.raises(ToolError) as error:
        get_compatible_products(context, memory, GetCompatibleProductsArgs(device="iPhone"))

    assert error.value.code is ToolErrorCode.DEVICE_AMBIGUOUS
    identifiers = [c["identifier"] for c in error.value.details["candidates"]]
    assert identifiers == ["iphone_15", "iphone_16"]


def test_the_ranker_receives_a_resolved_target_never_a_phrase(
    context, memory, compatibility, recommendations
):
    """The type is what closes the ADR-003 pipeline: a device string the model
    wrote has no way to reach the ranking engine."""
    compatibility.targets["iPhone 16"] = IPHONE_16
    recommendations.result = make_recommendation(make_ranked(make_variant()))

    get_compatible_products(context, memory, GetCompatibleProductsArgs(device="iPhone 16"))

    target = recommendations.requirements[-1].compatibility_target
    assert isinstance(target, ResolvedTarget)
    assert target.canonical_identifier == "iphone_16"


def test_a_device_is_resolved_once_per_turn(context, memory, compatibility, recommendations):
    """A buyer should not be asked about their phone twice because two tools
    happened to need it."""
    compatibility.targets["iPhone 16"] = IPHONE_16
    recommendations.result = make_recommendation(make_ranked(make_variant()))

    get_compatible_products(context, memory, GetCompatibleProductsArgs(device="iPhone 16"))
    get_compatible_products(context, memory, GetCompatibleProductsArgs(device="iPhone 16"))

    assert memory.resolved_devices["iPhone 16"] is IPHONE_16


# --------------------------------------------------------------------------
# check_inventory (T4)
# --------------------------------------------------------------------------


def test_out_of_stock_is_an_answer_rather_than_an_error(context, memory, catalog, inventory):
    """The agent has to be able to say "that one is unavailable, here is what
    is", which it can only do if the call returned facts."""
    variant = make_variant(sku="CASE-OOS")
    catalog.variants_by_sku["CASE-OOS"] = variant
    inventory.stock[variant.id] = StockView(
        variant_id=variant.id, quantity=0, reserved_quantity=0, status=StockStatus.OUT_OF_STOCK
    )

    result = check_inventory(context, memory, CheckInventoryArgs(sku="CASE-OOS"))

    assert result["available"] is False
    assert result["stock_status"] == "OUT_OF_STOCK"


def test_availability_compares_against_the_requested_quantity(context, memory, catalog, inventory):
    """D§29 step 6: enough for what was asked, not merely non-zero."""
    variant = make_variant(sku="CASE-TWO")
    catalog.variants_by_sku["CASE-TWO"] = variant
    inventory.stock[variant.id] = StockView(
        variant_id=variant.id, quantity=2, reserved_quantity=0, status=StockStatus.LOW_STOCK
    )

    two = check_inventory(context, memory, CheckInventoryArgs(sku="CASE-TWO", quantity=2))
    three = check_inventory(context, memory, CheckInventoryArgs(sku="CASE-TWO", quantity=3))

    assert two["available"] is True
    assert three["available"] is False


def test_check_inventory_never_discloses_the_quantity(context, memory, catalog, inventory):
    """ADR-009, closing E5. Exact counts stay in the service and the Policy Engine."""
    variant = make_variant(sku="CASE-MANY")
    catalog.variants_by_sku["CASE-MANY"] = variant
    inventory.stock[variant.id] = StockView(
        variant_id=variant.id, quantity=137, reserved_quantity=0, status=StockStatus.IN_STOCK
    )

    result = check_inventory(context, memory, CheckInventoryArgs(sku="CASE-MANY"))

    assert "137" not in str(result)
    assert "available_quantity" not in result


def test_an_unknown_variant_is_an_error(context, memory):
    with pytest.raises(ToolError) as error:
        check_inventory(context, memory, CheckInventoryArgs(sku="NOPE"))

    assert error.value.code is ToolErrorCode.VARIANT_NOT_FOUND


# --------------------------------------------------------------------------
# get_upsell_candidates (T5, R§15)
# --------------------------------------------------------------------------


def test_upsell_starts_from_a_relationship_and_can_be_empty(
    context, memory, catalog, recommendations
):
    """R§15: the system must not recommend random products merely because they
    increase revenue. Most products have no accessories, and an empty list is
    the correct answer rather than an invitation to find something."""
    variant = make_variant()
    catalog.products[variant.product_id] = ProductDetail(
        product=ProductSummary(
            id=variant.product_id, slug="p", name="P", category_slug="phone_case"
        ),
        variants=(variant,),
    )
    recommendations.cross_sell = []

    result = get_upsell_candidates(
        context, memory, GetUpsellCandidatesArgs(product_id=str(variant.product_id))
    )

    assert result["candidates"] == []


def test_upsell_refuses_a_product_that_does_not_exist(context, memory):
    with pytest.raises(ToolError) as error:
        get_upsell_candidates(
            context, memory, GetUpsellCandidatesArgs(product_id=str(uuid.uuid4()))
        )

    assert error.value.code is ToolErrorCode.PRODUCT_NOT_FOUND


def test_upsell_with_an_unresolvable_device_asks_rather_than_offering_anything(
    context, memory, catalog
):
    """Silently dropping the device would offer accessories that do not fit."""
    variant = make_variant()
    catalog.products[variant.product_id] = ProductDetail(
        product=ProductSummary(
            id=variant.product_id, slug="p", name="P", category_slug="phone_case"
        ),
        variants=(variant,),
    )

    with pytest.raises(ToolError) as error:
        get_upsell_candidates(
            context,
            memory,
            GetUpsellCandidatesArgs(product_id=str(variant.product_id), device="whatever"),
        )

    assert error.value.code is ToolErrorCode.DEVICE_NOT_RESOLVED
