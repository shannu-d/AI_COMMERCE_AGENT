"""The aggregator, the ordering, Top-K, and the three outcomes.

The first test in this file is the **M3 exit condition**: ADR-004 requires the
R§10 worked example to reproduce under the `explainability_demo` profile —
AeroCase Pro ≈ 0.797, ShieldCase Premium ≈ 0.787 — proving the aggregator
matches the specification's own arithmetic rather than merely resembling it.
"""

from __future__ import annotations

import random
from decimal import Decimal

import pytest

from app.domain import (
    HardConstraint,
    ProductRequirement,
    RecommendationLabel,
    RecommendationOutcome,
    StockStatus,
)
from app.ranking import aggregate, get_profile, rank, recommend
from app.ranking.ranker import DEFAULT_TOP_K, score_variant
from app.ranking.scorers import price_denominator
from tests.ranking.conftest import MERCHANT_ID, make_variant, out_of_stock, stock_for

# --------------------------------------------------------------------------
# M3 exit condition — the R§10 worked example
# --------------------------------------------------------------------------


def test_r10_worked_example_reproduces_exactly() -> None:
    """`architecture.md` R§10, arithmetic and all.

        Product A: (0.40 x 1.0) + (0.30 x 0.8) + (0.20 x 0.334) + (0.10 x 0.9) = 0.7968
        Product B: (0.40 x 1.0) + (0.30 x 0.9) + (0.20 x 0.134) + (0.10 x 0.9) = 0.7868

    The feature scores are the ones the specification states, so this isolates
    the aggregator: if the weighted sum is wrong, this fails regardless of what
    the scorers do. ADR-004 names it as the milestone's exit test.
    """
    profile = get_profile("explainability_demo")

    aerocase = aggregate(
        profile,
        preference=Decimal("0.8"),
        price=Decimal("0.334"),
        relevance=Decimal("0.9"),
        compatibility=Decimal("1.0"),
    )
    shieldcase = aggregate(
        profile,
        preference=Decimal("0.9"),
        price=Decimal("0.134"),
        relevance=Decimal("0.9"),
        compatibility=Decimal("1.0"),
    )

    assert aerocase.final_score == Decimal("0.796800")
    assert shieldcase.final_score == Decimal("0.786800")
    assert aerocase.final_score > shieldcase.final_score


def test_r10_component_contributions_are_the_documented_ones() -> None:
    """RULE 10: explainable means the arithmetic is inspectable, not just the total."""
    breakdown = aggregate(
        get_profile("explainability_demo"),
        preference=Decimal("0.8"),
        price=Decimal("0.334"),
        relevance=Decimal("0.9"),
        compatibility=Decimal("1.0"),
    )

    contributions = {c.name: c.contribution for c in breakdown.components}

    assert contributions["compatibility"] == Decimal("0.400")
    assert contributions["preference"] == Decimal("0.240")
    assert contributions["price"] == Decimal("0.06680")
    assert contributions["relevance"] == Decimal("0.090")


def test_r10_price_scores_come_out_of_the_scorer_not_the_fixture(aerocase, shieldcase) -> None:
    """The other half of the worked example: the ₹999 and ₹1,299 products,
    against the stated ₹1,500 budget, score 0.334 and 0.134."""
    candidates = [aerocase, shieldcase]
    denominator = price_denominator(candidates, Decimal("1500"))
    requirement = ProductRequirement(label="phone_case", max_price=Decimal("1500"))
    profile = get_profile("explainability_demo")

    scores = {
        v.sku: score_variant(v, requirement, profile=profile, denominator=denominator)
        for v in candidates
    }

    assert scores["CASE-IP16-BLK"].component("price").score == Decimal("0.334000")
    assert scores["CASE-IP16-SHD-BLK"].component("price").score == Decimal("0.134000")


def test_the_full_pipeline_ranks_aerocase_first(aerocase, shieldcase, iphone_16) -> None:
    """R§10 end to end: "I have an iPhone 16. I need a good case under ₹1,500."

    Every number here is computed — filter, four scorers, weights, sort — rather
    than supplied. AeroCase Pro leads on price attractiveness, which is what the
    specification's own worked example concludes.
    """
    requirement = ProductRequirement(
        label="phone_case",
        category_slug="phone_case",
        query_text="good case",
        max_price=Decimal("1500"),
        compatibility_target=iphone_16,
    )
    candidates = [aerocase, shieldcase]

    result = recommend(
        candidates,
        requirement,
        merchant_id=MERCHANT_ID,
        stock=stock_for(candidates),
        compatible_product_ids={aerocase.product_id, shieldcase.product_id},
        profile="explainability_demo",
    )

    assert result.outcome is RecommendationOutcome.EXACT_MATCH
    assert [c.variant.sku for c in result.candidates] == ["CASE-IP16-BLK", "CASE-IP16-SHD-BLK"]
    assert result.candidates[0].final_score > result.candidates[1].final_score


# --------------------------------------------------------------------------
# The aggregator
# --------------------------------------------------------------------------


def test_the_default_profile_emits_no_compatibility_component() -> None:
    """R§19's three-weight form. Compatibility is a filter, so there is nothing
    to report about it — every survivor is compatible by construction."""
    breakdown = aggregate(
        get_profile(),
        preference=Decimal("1"),
        price=Decimal("1"),
        relevance=Decimal("1"),
        compatibility=Decimal("1"),
    )

    assert [c.name for c in breakdown.components] == ["preference", "price", "relevance"]
    assert breakdown.final_score == Decimal("1.000000")


def test_a_perfect_candidate_scores_one_under_every_profile() -> None:
    """The weights sum to 1, so a candidate perfect on every feature scores 1.0
    whichever profile ran. Any other result means a weight is missing."""
    for name in ("default", "price_sensitive", "premium", "explainability_demo"):
        breakdown = aggregate(
            get_profile(name),
            preference=Decimal("1"),
            price=Decimal("1"),
            relevance=Decimal("1"),
            compatibility=Decimal("1"),
        )

        assert breakdown.final_score == Decimal("1.000000"), name


def test_the_zero_preference_ceiling_is_real_and_documented() -> None:
    """ADR-004 warns that with no stated preferences no candidate can exceed the
    remaining weights. Asserted here so a future `FinalScore` threshold cannot
    be written in ignorance of it."""
    breakdown = aggregate(
        get_profile(),
        preference=Decimal("0"),
        price=Decimal("1"),
        relevance=Decimal("1"),
    )

    assert breakdown.final_score == Decimal("0.500000")


def test_the_profile_name_travels_with_the_score() -> None:
    """A score is only reproducible if you know which weights produced it."""
    breakdown = aggregate(
        get_profile("premium"),
        preference=Decimal("1"),
        price=Decimal("0"),
        relevance=Decimal("0"),
    )

    assert breakdown.profile_name == "premium"
    assert breakdown.final_score == Decimal("0.700000")


# --------------------------------------------------------------------------
# Ordering and determinism (RULE 8)
# --------------------------------------------------------------------------


def test_ranking_is_ordered_by_descending_score() -> None:
    candidates = [
        make_variant("C", "1400.00", attributes={"color": "blue"}),
        make_variant("A", "500.00", attributes={"color": "black"}),
        make_variant("B", "900.00", attributes={"color": "black"}),
    ]
    requirement = ProductRequirement(
        label="phone_case", max_price=Decimal("1500"), preferences={"color": "black"}
    )

    ranked = rank(candidates, requirement, top_k=10)

    scores = [c.final_score for c in ranked]
    assert scores == sorted(scores, reverse=True)
    assert [c.variant.sku for c in ranked] == ["A", "B", "C"]


def test_a_score_tie_breaks_on_the_lower_price() -> None:
    """Two identical products at different prices: the cheaper places first.

    They cannot tie on score — price is a scored feature — so this uses the
    `premium` profile, where price carries so little weight that the six-decimal
    scores collide.
    """
    candidates = [
        make_variant("DEAR", "1000.00", attributes={"color": "black"}),
        make_variant("CHEAP", "999.99", attributes={"color": "black"}),
    ]
    requirement = ProductRequirement(label="phone_case", preferences={"color": "black"})

    ranked = rank(candidates, requirement, profile="premium", top_k=10)

    assert [c.variant.sku for c in ranked] == ["CHEAP", "DEAR"]


def test_a_price_tie_breaks_on_the_sku() -> None:
    """The colours of one product at one price. SKU is unique per merchant, so
    the ordering is total — which is what RULE 8 requires."""
    candidates = [
        make_variant("CASE-IP16-BLU", "999.00", name="Blue"),
        make_variant("CASE-IP16-BLK", "999.00", name="Black"),
    ]
    requirement = ProductRequirement(label="phone_case")

    ranked = rank(candidates, requirement, top_k=10)

    assert [c.variant.sku for c in ranked] == ["CASE-IP16-BLK", "CASE-IP16-BLU"]


def test_the_same_input_in_any_order_produces_the_same_output() -> None:
    """RULE 8. An unstable sort would make the same request answer differently
    depending on the order rows happened to come back from PostgreSQL."""
    candidates = [
        make_variant(f"SKU-{i:02d}", f"{999 - (i % 3) * 100}.00", attributes={"color": "black"})
        for i in range(12)
    ]
    requirement = ProductRequirement(
        label="phone_case", max_price=Decimal("1500"), preferences={"color": "black"}
    )
    expected = [c.variant.sku for c in rank(candidates, requirement, top_k=5)]

    shuffler = random.Random(20260831)
    for _ in range(10):
        shuffled = candidates[:]
        shuffler.shuffle(shuffled)

        assert [c.variant.sku for c in rank(shuffled, requirement, top_k=5)] == expected


def test_ranking_the_same_set_twice_returns_identical_scores() -> None:
    """R§11: reproducible. No clock, no randomness, no floating point."""
    candidates = [make_variant("A", "999.00"), make_variant("B", "1299.00")]
    requirement = ProductRequirement(label="phone_case", max_price=Decimal("1500"))

    first = rank(candidates, requirement)
    second = rank(candidates, requirement)

    assert [c.final_score for c in first] == [c.final_score for c in second]


# --------------------------------------------------------------------------
# Top-K (RULE 11)
# --------------------------------------------------------------------------


def test_top_k_defaults_to_three() -> None:
    """RULE 11: "a small number of strong candidates, preferably Top 3"."""
    candidates = [make_variant(f"SKU-{i}", f"{100 * (i + 1)}.00") for i in range(10)]

    ranked = rank(candidates, ProductRequirement(label="phone_case"))

    assert DEFAULT_TOP_K == 3
    assert len(ranked) == 3


def test_top_k_keeps_the_highest_scoring_candidates() -> None:
    candidates = [make_variant(f"SKU-{i}", f"{100 * (i + 1)}.00") for i in range(10)]

    ranked = rank(candidates, ProductRequirement(label="phone_case"), top_k=3)

    assert [c.variant.sku for c in ranked] == ["SKU-0", "SKU-1", "SKU-2"]


def test_ranks_are_one_based_and_contiguous() -> None:
    candidates = [make_variant(f"SKU-{i}", f"{100 * (i + 1)}.00") for i in range(5)]

    ranked = rank(candidates, ProductRequirement(label="phone_case"), top_k=4)

    assert [c.rank for c in ranked] == [1, 2, 3, 4]


def test_top_k_per_requirement_not_per_request(aerocase, shieldcase) -> None:
    """ADR-004, closing open question A6: "a case and a charger" yields three
    cases *and* three chargers, not three items overall.

    Each requirement is ranked in its own call, so the cut cannot be shared.
    """
    cases = [make_variant(f"CASE-{i}", f"{900 + i}.00") for i in range(5)]
    chargers = [
        make_variant(f"CHG-{i}", f"{1000 + i}.00", category_slug="charger") for i in range(5)
    ]

    case_ranked = rank(cases, ProductRequirement(label="phone_case"))
    charger_ranked = rank(chargers, ProductRequirement(label="charger"))

    assert len(case_ranked) == 3
    assert len(charger_ranked) == 3


def test_ranking_an_empty_set_is_empty() -> None:
    assert rank([], ProductRequirement(label="phone_case")) == ()


# --------------------------------------------------------------------------
# Stock status disclosure
# --------------------------------------------------------------------------


def test_ranked_candidates_carry_coarse_stock_status_only() -> None:
    """ADR-009/ADR-010 (open question E5): the buyer sees a status, not a count.

    Exact quantities stay inside the services and the Policy Engine — telling a
    buyer there are three left is a merchandising decision nobody made.
    """
    variant = make_variant("LOW", "999.00")
    stock = stock_for([variant], quantity=3)

    ranked = rank([variant], ProductRequirement(label="phone_case"), stock=stock)

    assert ranked[0].stock_status is StockStatus.LOW_STOCK
    assert not hasattr(ranked[0], "quantity")


# --------------------------------------------------------------------------
# The three outcomes (ADR-005, R§14)
# --------------------------------------------------------------------------


def test_survivors_produce_an_exact_match(aerocase) -> None:
    result = recommend(
        [aerocase],
        ProductRequirement(label="phone_case", category_slug="phone_case"),
        merchant_id=MERCHANT_ID,
        stock=stock_for([aerocase]),
    )

    assert result.outcome is RecommendationOutcome.EXACT_MATCH
    assert result.alternatives == ()


def test_an_over_budget_product_becomes_a_labelled_alternative() -> None:
    """ADR-005's own example: "no leather case under ₹500, but there is a
    leather case at ₹1,799" — offered, and *named* as over budget, rather than
    presented as a match or hidden."""
    folio = make_variant(
        "CASE-IP16-LTR-BLK",
        "1799.00",
        product_slug="leatherline_folio",
        product_attributes={"material": "leather"},
    )
    requirement = ProductRequirement(
        label="phone_case",
        category_slug="phone_case",
        max_price=Decimal("500"),
        preferences={"material": "leather"},
    )

    result = recommend(
        [folio],
        requirement,
        merchant_id=MERCHANT_ID,
        stock=stock_for([folio]),
    )

    assert result.outcome is RecommendationOutcome.NO_MATCH_WITH_ALTERNATIVES
    assert result.candidates == ()
    assert [c.variant.sku for c in result.alternatives] == ["CASE-IP16-LTR-BLK"]
    assert result.relaxed_constraints == (HardConstraint.BUDGET,)


def test_alternatives_are_never_returned_in_the_candidates_field() -> None:
    """The separation is the safety property: nothing downstream can mistake an
    alternative for a match, because they are different fields."""
    folio = make_variant("LTR", "1799.00")
    requirement = ProductRequirement(label="phone_case", max_price=Decimal("500"))

    result = recommend([folio], requirement, merchant_id=MERCHANT_ID, stock=stock_for([folio]))

    assert result.candidates == ()
    assert result.has_match is False


def test_an_incompatible_product_is_never_offered_as_an_alternative(
    iphone_15_case, iphone_16
) -> None:
    """ADR-005: compatibility is the one constraint never relaxed. A case for a
    different phone is not an alternative, it is a wrong answer."""
    requirement = ProductRequirement(
        label="phone_case", category_slug="phone_case", compatibility_target=iphone_16
    )

    result = recommend(
        [iphone_15_case],
        requirement,
        merchant_id=MERCHANT_ID,
        stock=stock_for([iphone_15_case]),
        compatible_product_ids=set(),
    )

    assert result.outcome is RecommendationOutcome.NO_MATCH
    assert result.alternatives == ()


def test_an_out_of_stock_product_is_never_offered_as_an_alternative() -> None:
    """RULE 5. An alternative the buyer cannot buy is not an alternative."""
    variant = make_variant("GONE", "949.00")
    requirement = ProductRequirement(label="phone_case", category_slug="phone_case")

    result = recommend(
        [variant],
        requirement,
        merchant_id=MERCHANT_ID,
        stock={variant.id: out_of_stock(variant)},
    )

    assert result.outcome is RecommendationOutcome.NO_MATCH
    assert result.alternatives == ()


def test_nothing_relevant_at_all_is_a_plain_no_match() -> None:
    """R§14: do not fabricate a product, do not relax compatibility silently,
    do not invent availability. Returning nothing is the correct answer."""
    result = recommend(
        [],
        ProductRequirement(label="phone_case", category_slug="phone_case"),
        merchant_id=MERCHANT_ID,
        stock={},
    )

    assert result.outcome is RecommendationOutcome.NO_MATCH
    assert result.candidates == ()
    assert result.alternatives == ()


def test_alternatives_are_scored_without_the_budget_that_excluded_them() -> None:
    """Keeping the buyer's budget as the price denominator would drive every
    over-budget candidate below zero, where the clamp flattens them into a
    meaningless tie. With the budget relaxed there is no budget, so the
    candidate-set denominator applies — the same rule any unbudgeted request
    uses.
    """
    dear = make_variant("DEAR", "3000.00")
    less_dear = make_variant("LESS", "1600.00")
    requirement = ProductRequirement(label="phone_case", max_price=Decimal("1500"))

    result = recommend(
        [dear, less_dear],
        requirement,
        merchant_id=MERCHANT_ID,
        stock=stock_for([dear, less_dear]),
    )

    prices = [c.score.component("price").score for c in result.alternatives]
    assert [c.variant.sku for c in result.alternatives] == ["LESS", "DEAR"]
    assert prices[0] > prices[1] > Decimal("0") - Decimal("1")
    assert len(set(prices)) == 2, "clamped alternatives would tie and lose their order"


def test_the_rejection_record_survives_into_the_result(aerocase, iphone_15_case) -> None:
    """RULE 10: the ranker can say what it removed and why, which is what makes
    the alternatives honest rather than merely permitted."""
    requirement = ProductRequirement(label="phone_case", max_price=Decimal("950"))
    candidates = [aerocase, iphone_15_case]

    result = recommend(
        candidates,
        requirement,
        merchant_id=MERCHANT_ID,
        stock=stock_for(candidates),
    )

    rejected = {r.variant.sku: r.primary.constraint for r in result.rejected}
    assert rejected["CASE-IP16-BLK"] is HardConstraint.BUDGET


# --------------------------------------------------------------------------
# The boundary
# --------------------------------------------------------------------------


def test_the_ranker_refuses_an_unknown_profile_name() -> None:
    with pytest.raises(ValueError, match="known profiles"):
        rank([], ProductRequirement(label="phone_case"), profile="whatever_the_model_said")


def test_no_weight_profile_can_promote_an_incompatible_product(
    aerocase, iphone_15_case, iphone_16
) -> None:
    """The regression ADR-005 asks for, run against every profile that exists.

    "There is no configuration in which a cheap incompatible product can outrank
    a compatible one." The iPhone 15 case is ₹100 cheaper and identical in every
    other respect.
    """
    requirement = ProductRequirement(
        label="phone_case",
        category_slug="phone_case",
        max_price=Decimal("1500"),
        compatibility_target=iphone_16,
    )
    candidates = [aerocase, iphone_15_case]

    for profile in ("default", "price_sensitive", "premium", "explainability_demo"):
        result = recommend(
            candidates,
            requirement,
            merchant_id=MERCHANT_ID,
            stock=stock_for(candidates),
            compatible_product_ids={aerocase.product_id},
            profile=profile,
        )

        assert [c.variant.sku for c in result.candidates] == ["CASE-IP16-BLK"], profile
        assert result.alternatives == (), profile


def test_the_ranked_reason_is_a_label_the_engine_derived() -> None:
    """ADR-004 (open question A7): the ranking engine writes the reason.

    `RecommendationLabel` is a closed enum, so there is no field on a ranked
    candidate that free text — model-authored or otherwise — could occupy.
    """
    candidates = [make_variant("A", "500.00"), make_variant("B", "1400.00")]

    ranked = rank(candidates, ProductRequirement(label="phone_case", max_price=Decimal("1500")))

    for candidate in ranked:
        assert isinstance(candidate.explanation.label, RecommendationLabel)
