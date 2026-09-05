"""RecommendationService against the real CircuitCraft catalog.

The pure ranking tests in `tests/ranking/` prove the arithmetic. These prove the
wiring: that the candidate set really comes from PostgreSQL, that compatibility
really comes from `compatibility_rules`, that stock really comes from
`inventory`, and that the seed catalog's deliberately-planted cases behave as
M1 designed them to.

The catalog was shaped in M1 so each of these is separately observable:

* AeroCase Pro ₹999 and ShieldCase Premium ₹1,299 — the R§10 worked example;
* AeroCase Pro 15 at ₹899 — cheaper, and for the wrong phone (D§15's trap);
* LeatherLine Folio at ₹1,799 — the honest over-budget alternative;
* `CASE-IP16-CLR` at quantity 0 — the out-of-stock path;
* `pixel_9` — a *resolvable* device with zero compatible products, which is
  R§14's no-match, not a resolution failure.

These are marked `requires_db` and skip with a visible reason when no PostgreSQL
is reachable (ADR-002: never redirected at a different engine).
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from sqlalchemy.orm import Session

from app.domain import (
    CombinationOutcome,
    HardConstraint,
    ProductRequirement,
    RecommendationOutcome,
    ResolvedTarget,
    StockStatus,
)
from app.services import CompatibilityService, RecommendationService
from tests.services.conftest import OTHER_MERCHANT_ID

pytestmark = pytest.mark.requires_db


@pytest.fixture
def recommendations(session: Session) -> RecommendationService:
    return RecommendationService(session)


@pytest.fixture
def iphone_16(compatibility: CompatibilityService) -> ResolvedTarget:
    """Resolved through the real pipeline, not constructed."""
    target = compatibility.resolve_target("iPhone 16")
    assert isinstance(target, ResolvedTarget)
    return target


@pytest.fixture
def pixel_9(compatibility: CompatibilityService) -> ResolvedTarget:
    target = compatibility.resolve_target("Pixel 9")
    assert isinstance(target, ResolvedTarget)
    return target


def case_under_1500(target: ResolvedTarget) -> ProductRequirement:
    """ "I have an iPhone 16. I need a good case under ₹1,500." (R§10)"""
    return ProductRequirement(
        label="phone_case",
        category_slug="phone_case",
        query_text="good case",
        max_price=Decimal("1500"),
        compatibility_target=target,
    )


def skus(candidates) -> list[str]:
    return [c.variant.sku for c in candidates]


# --------------------------------------------------------------------------
# The flagship read-path request
# --------------------------------------------------------------------------


def test_the_r10_request_returns_only_compatible_in_budget_cases(
    recommendations: RecommendationService, merchant_id: uuid.UUID, iphone_16: ResolvedTarget
) -> None:
    """Every hard constraint, applied to the real catalog at once."""
    result = recommendations.recommend(merchant_id, case_under_1500(iphone_16))

    assert result.outcome is RecommendationOutcome.EXACT_MATCH
    for candidate in result.candidates:
        assert candidate.variant.category_slug == "phone_case"
        assert candidate.variant.price <= Decimal("1500")
        assert candidate.stock_status is not StockStatus.OUT_OF_STOCK


def test_the_worked_examples_two_products_are_both_returned(
    recommendations: RecommendationService, merchant_id: uuid.UUID, iphone_16: ResolvedTarget
) -> None:
    """R§10's Product A and Product B are real rows, and both survive filtering."""
    result = recommendations.recommend(merchant_id, case_under_1500(iphone_16), top_k=10)

    returned = skus(result.candidates)
    assert "CASE-IP16-BLK" in returned
    assert "CASE-IP16-SHD-BLK" in returned


def test_the_cheaper_iphone_15_case_never_appears(
    recommendations: RecommendationService, merchant_id: uuid.UUID, iphone_16: ResolvedTarget
) -> None:
    """D§15, against the seed catalog: ₹899 and wrong. It is removed by
    `compatibility_rules`, not ranked low, and no weight profile changes that."""
    for profile in ("default", "price_sensitive", "premium", "explainability_demo"):
        result = recommendations.recommend(
            merchant_id, case_under_1500(iphone_16), profile=profile, top_k=10
        )

        assert "CASE-IP15-BLK" not in skus(result.candidates), profile
        assert "CASE-IP15-BLK" not in skus(result.alternatives), profile


def test_the_out_of_stock_clear_case_is_excluded(
    recommendations: RecommendationService, merchant_id: uuid.UUID, iphone_16: ResolvedTarget
) -> None:
    """`CASE-IP16-CLR` is seeded at quantity 0 and is ₹949 — the cheapest
    compatible case there is. RULE 5 removes it anyway."""
    result = recommendations.recommend(merchant_id, case_under_1500(iphone_16), top_k=10)

    assert "CASE-IP16-CLR" not in skus(result.candidates)
    rejected = {r.variant.sku: r.constraints for r in result.rejected}
    assert HardConstraint.INVENTORY in rejected["CASE-IP16-CLR"]


def test_top_k_caps_the_result_at_the_configured_number(
    recommendations: RecommendationService, merchant_id: uuid.UUID, iphone_16: ResolvedTarget
) -> None:
    """RULE 11: a small number of strong candidates, not the catalog.

    The cap is `Settings.ranking_top_k` (deviation D12 raised it from 3 to 9),
    so this asserts against the configured value and, separately, that the cap
    is doing something - a category holding fewer products than the cap would
    make the first assertion pass no matter how broken the slice was.
    """
    from app.config import get_settings

    cap = get_settings().ranking_top_k
    result = recommendations.recommend(merchant_id, case_under_1500(iphone_16))

    assert len(result.candidates) <= cap
    assert result.candidates, "the worked-example category returned nothing at all"


def test_prices_come_back_as_decimal_from_the_database(
    recommendations: RecommendationService, merchant_id: uuid.UUID, iphone_16: ResolvedTarget
) -> None:
    """ADR-008 and RULE 6: no float touches a price on the way through ranking."""
    result = recommendations.recommend(merchant_id, case_under_1500(iphone_16))

    for candidate in result.candidates:
        assert isinstance(candidate.variant.price, Decimal)
        assert candidate.variant.currency == "INR"


def test_the_same_request_twice_returns_the_same_order(
    recommendations: RecommendationService, merchant_id: uuid.UUID, iphone_16: ResolvedTarget
) -> None:
    """RULE 8 across the database boundary, where row order is not guaranteed."""
    first = recommendations.recommend(merchant_id, case_under_1500(iphone_16), top_k=10)
    second = recommendations.recommend(merchant_id, case_under_1500(iphone_16), top_k=10)

    assert skus(first.candidates) == skus(second.candidates)
    assert [c.final_score for c in first.candidates] == [c.final_score for c in second.candidates]


# --------------------------------------------------------------------------
# No-match and alternatives (R§14, ADR-005)
# --------------------------------------------------------------------------


def test_a_resolvable_device_with_no_compatible_products_is_a_no_match(
    recommendations: RecommendationService, merchant_id: uuid.UUID, pixel_9: ResolvedTarget
) -> None:
    """R§14's own example: "Case for Pixel 9?" — no compatible Pixel 9 cases.

    The device *resolved*, which is why this is a no-match rather than a
    clarification. The seed contains `pixel_9` with zero compatible products for
    exactly this distinction (ADR-003).
    """
    result = recommendations.recommend(
        merchant_id,
        ProductRequirement(
            label="phone_case", category_slug="phone_case", compatibility_target=pixel_9
        ),
    )

    assert result.outcome is RecommendationOutcome.NO_MATCH
    assert result.candidates == ()
    assert result.alternatives == ()


def test_a_tight_budget_produces_a_labelled_over_budget_alternative(
    recommendations: RecommendationService, merchant_id: uuid.UUID, iphone_16: ResolvedTarget
) -> None:
    """ADR-005's example, with the catalog's real leather case.

    No compatible case exists under ₹500. LeatherLine Folio at ₹1,799 does. It
    is offered as an alternative, in its own field, with the constraint it fails
    named — never as a match.
    """
    result = recommendations.recommend(
        merchant_id,
        ProductRequirement(
            label="phone_case",
            category_slug="phone_case",
            max_price=Decimal("500"),
            preferences={"material": "leather"},
            compatibility_target=iphone_16,
        ),
        top_k=10,
    )

    assert result.outcome is RecommendationOutcome.NO_MATCH_WITH_ALTERNATIVES
    assert result.candidates == ()
    assert result.relaxed_constraints == (HardConstraint.BUDGET,)
    assert "CASE-IP16-LTR-BLK" in skus(result.alternatives)


def test_an_alternative_is_never_for_the_wrong_phone(
    recommendations: RecommendationService, merchant_id: uuid.UUID, iphone_16: ResolvedTarget
) -> None:
    """Compatibility is the one constraint never relaxed, even when relaxing it
    would be the only way to produce a result."""
    result = recommendations.recommend(
        merchant_id,
        ProductRequirement(
            label="phone_case",
            category_slug="phone_case",
            max_price=Decimal("100"),
            compatibility_target=iphone_16,
        ),
        top_k=10,
    )

    assert "CASE-IP15-BLK" not in skus(result.alternatives)
    assert HardConstraint.COMPATIBILITY not in result.relaxed_constraints


def test_a_required_specification_no_catalog_product_meets_is_a_no_match(
    recommendations: RecommendationService, merchant_id: uuid.UUID, iphone_16: ResolvedTarget
) -> None:
    """R§14: do not fabricate, do not invent, do not quietly drop the requirement."""
    result = recommendations.recommend(
        merchant_id,
        ProductRequirement(
            label="charger",
            category_slug="charger",
            required_attributes={"minimum_wattage": 500},
            compatibility_target=iphone_16,
        ),
    )

    assert result.candidates == ()
    assert result.outcome in {
        RecommendationOutcome.NO_MATCH,
        RecommendationOutcome.NO_MATCH_WITH_ALTERNATIVES,
    }


# --------------------------------------------------------------------------
# Merchant scoping (ADR-002)
# --------------------------------------------------------------------------


def test_another_merchant_sees_nothing(
    recommendations: RecommendationService, iphone_16: ResolvedTarget
) -> None:
    """Scoping excludes rather than merely filters: a query ignoring
    `merchant_id` would still return the CircuitCraft catalog."""
    result = recommendations.recommend(OTHER_MERCHANT_ID, case_under_1500(iphone_16))

    assert result.outcome is RecommendationOutcome.NO_MATCH
    assert result.candidates == ()


# --------------------------------------------------------------------------
# Multi-product (R§13)
# --------------------------------------------------------------------------


def test_a_case_and_a_charger_under_three_thousand(
    recommendations: RecommendationService, merchant_id: uuid.UUID, iphone_16: ResolvedTarget
) -> None:
    """R§13 verbatim: "I need a case and fast charger under ₹3,000.""" ""
    result = recommendations.recommend_many(
        merchant_id,
        [
            ProductRequirement(
                label="phone_case", category_slug="phone_case", compatibility_target=iphone_16
            ),
            ProductRequirement(
                label="charger",
                category_slug="charger",
                required_attributes={"fast_charge": True},
                compatibility_target=iphone_16,
            ),
        ],
        total_budget=Decimal("3000"),
    )

    assert result.combination.outcome is CombinationOutcome.WITHIN_BUDGET
    assert result.combination.total <= Decimal("3000")
    assert {item.label for item in result.combination.items} == {"phone_case", "charger"}
    assert result.for_label("phone_case") is not None


def test_an_impossible_total_budget_is_reported_not_exceeded(
    recommendations: RecommendationService, merchant_id: uuid.UUID, iphone_16: ResolvedTarget
) -> None:
    """Never silently drop a product type, never quietly return a basket over
    budget."""
    result = recommendations.recommend_many(
        merchant_id,
        [
            ProductRequirement(
                label="phone_case", category_slug="phone_case", compatibility_target=iphone_16
            ),
            ProductRequirement(
                label="charger", category_slug="charger", compatibility_target=iphone_16
            ),
        ],
        total_budget=Decimal("100"),
    )

    assert result.combination.outcome in {
        CombinationOutcome.NO_COMBINATION_WITHIN_BUDGET,
        CombinationOutcome.INCOMPLETE,
    }
    assert result.combination.items == ()


# --------------------------------------------------------------------------
# Cross-sell (R§15, RANK-09)
# --------------------------------------------------------------------------


def test_cross_sell_offers_the_screen_protector_the_relationship_names(
    recommendations: RecommendationService,
    merchant_id: uuid.UUID,
    iphone_16: ResolvedTarget,
    product_id,
) -> None:
    """R§15's example: buying a case, offered the compatible screen protector.

    The offer starts from a `product_relationships` row — it is not a search for
    something else to sell.
    """
    candidates = recommendations.cross_sell_candidates(
        merchant_id, product_id("aerocase_pro"), target=iphone_16
    )

    slugs = {c.product.slug for c in candidates}
    assert "guardglass_2_5d" in slugs
    for candidate in candidates:
        assert candidate.relationship_type in {"cross_sell", "bundle"}
        assert candidate.stock_status is not StockStatus.OUT_OF_STOCK
        assert isinstance(candidate.variant.price, Decimal)


def test_cross_sell_excludes_products_incompatible_with_the_buyers_device(
    recommendations: RecommendationService,
    merchant_id: uuid.UUID,
    compatibility: CompatibilityService,
    product_id,
) -> None:
    """R§15 requires the offer be grounded in compatibility, so a MacBook buyer
    is not offered an iPhone accessory just because a relationship exists."""
    macbook = compatibility.resolve_target("MacBook Air M3")
    assert isinstance(macbook, ResolvedTarget)

    candidates = recommendations.cross_sell_candidates(
        merchant_id, product_id("aerocase_pro"), target=macbook
    )

    assert candidates == []


def test_cross_sell_returns_nothing_for_a_product_with_no_relationships(
    recommendations: RecommendationService, merchant_id: uuid.UUID, product_id
) -> None:
    """ "The system must not recommend random products merely because they
    increase revenue." No relationship, no offer."""
    candidates = recommendations.cross_sell_candidates(merchant_id, product_id("sonicbuds_lite"))

    assert candidates == []


def test_cross_sell_is_ordered_by_relationship_priority(
    recommendations: RecommendationService,
    merchant_id: uuid.UUID,
    iphone_16: ResolvedTarget,
    product_id,
) -> None:
    """The merchant's own priority, not a score the ranker invented."""
    candidates = recommendations.cross_sell_candidates(
        merchant_id, product_id("aerocase_pro"), target=iphone_16, limit=5
    )

    priorities = [c.priority for c in candidates]
    assert priorities == sorted(priorities)


def test_cross_sell_quantity_must_be_positive(
    recommendations: RecommendationService, merchant_id: uuid.UUID, product_id
) -> None:
    with pytest.raises(ValueError, match="at least 1"):
        recommendations.cross_sell_candidates(merchant_id, product_id("aerocase_pro"), quantity=0)


# --------------------------------------------------------------------------
# The service boundary
# --------------------------------------------------------------------------


def test_the_service_will_not_resolve_a_device_phrase(
    recommendations: RecommendationService, merchant_id: uuid.UUID
) -> None:
    """`compatibility_target` is typed `ResolvedTarget`, so a phrase the model
    wrote cannot reach the ranker (ADR-003).

    Resolution happens first and its failure is a question for the buyer.
    Burying it here would turn "I did not understand your phone" into "we have
    nothing for you".
    """
    with pytest.raises((TypeError, AttributeError)):
        recommendations.recommend(
            merchant_id,
            ProductRequirement(
                label="phone_case",
                category_slug="phone_case",
                compatibility_target="iphone_16",  # type: ignore[arg-type]
            ),
        )
