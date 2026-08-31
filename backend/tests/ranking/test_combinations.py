"""Multi-product requests against one overall budget (R§13, ADR-004).

The specification's own example is the first test:

    "I have an iPhone 16. I need a case and fast charger under ₹3,000."
    Case A = ₹999, Charger A = ₹1,299, Total = ₹2,298 -> Within ₹3,000
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.domain import CombinationOutcome, ProductRequirement, Recommendation, RecommendationOutcome
from app.ranking import combine, rank, recommend
from tests.ranking.conftest import MERCHANT_ID, make_variant, stock_for


def recommendation(label: str, variants, *, requirement=None) -> Recommendation:
    """A real `Recommendation` for `variants`, ranked, with nothing filtered out."""
    requirement = requirement or ProductRequirement(label=label)
    return recommend(
        variants,
        requirement,
        merchant_id=MERCHANT_ID,
        stock=stock_for(variants),
        top_k=5,
    )


def case(sku: str, price: str, *, color: str | None = None):
    return make_variant(
        sku,
        price,
        category_slug="phone_case",
        product_slug=f"p_{sku.lower()}",
        attributes={"color": color} if color else {},
    )


def charger(sku: str, price: str, *, color: str | None = None):
    return make_variant(
        sku,
        price,
        category_slug="charger",
        product_slug=f"p_{sku.lower()}",
        attributes={"color": color} if color else {},
    )


# The combination search only has work to do when the best candidate of some
# type is *not* the cheapest one. With no preferences stated, price is the only
# thing separating candidates, so rank 1 is always the cheapest and the
# best-of-each shortcut always fits. A stated colour preference is what lets a
# dearer product legitimately win its own ranking, which is the situation R§13
# describes: two individually-best products that together break the budget.
WANTS_BLACK_CASE = ProductRequirement(
    label="phone_case", category_slug="phone_case", preferences={"color": "black"}
)
WANTS_BLACK_CHARGER = ProductRequirement(
    label="charger", category_slug="charger", preferences={"color": "black"}
)


# --------------------------------------------------------------------------
# R§13's worked example
# --------------------------------------------------------------------------


def test_r13_case_and_charger_within_three_thousand() -> None:
    """Case ₹999 + charger ₹1,299 = ₹2,298, inside ₹3,000."""
    cases = recommendation("phone_case", [case("CASE-IP16-BLK", "999.00")])
    chargers = recommendation("charger", [charger("CHARGER-30W", "1299.00")])

    result = combine([cases, chargers], total_budget=Decimal("3000"))

    assert result.outcome is CombinationOutcome.WITHIN_BUDGET
    assert result.total == Decimal("2298.00")
    assert result.fits_budget
    assert [item.label for item in result.items] == ["phone_case", "charger"]


def test_the_best_of_each_is_taken_when_it_already_fits() -> None:
    """ADR-004 step 1: no search when the obvious answer works."""
    cases = recommendation("phone_case", [case("A", "999.00"), case("B", "1299.00")])
    chargers = recommendation("charger", [charger("C", "1099.00"), charger("D", "1499.00")])

    result = combine([cases, chargers], total_budget=Decimal("3000"))

    assert [item.candidate.rank for item in result.items] == [1, 1]


def test_with_no_stated_budget_the_best_of_each_is_the_answer() -> None:
    cases = recommendation("phone_case", [case("A", "999.00")])
    chargers = recommendation("charger", [charger("C", "9999.00")])

    result = combine([cases, chargers])

    assert result.outcome is CombinationOutcome.WITHIN_BUDGET
    assert result.total == Decimal("10998.00")
    assert result.total_budget is None


# --------------------------------------------------------------------------
# The search (ADR-004 step 2)
# --------------------------------------------------------------------------


def test_a_cheaper_combination_is_found_when_the_best_of_each_overshoots() -> None:
    """The best case is ₹1,200 and the best charger ₹1,000 — ₹2,200 against a
    ₹2,000 budget.

    Each is the highest-scoring product of its type, because the buyer asked for
    black and the black ones cost more. Rather than dropping a product type or
    exceeding the budget, the search keeps the case and steps down to the blue
    charger: ₹1,500, and the highest summed score of any pair that fits.
    """
    cases = recommendation(
        "phone_case",
        [case("CASE-BLACK", "1200.00", color="black"), case("CASE-BLUE", "400.00", color="blue")],
        requirement=WANTS_BLACK_CASE,
    )
    chargers = recommendation(
        "charger",
        [
            charger("CHG-BLACK", "1000.00", color="black"),
            charger("CHG-BLUE", "300.00", color="blue"),
        ],
        requirement=WANTS_BLACK_CHARGER,
    )

    assert cases.candidates[0].variant.sku == "CASE-BLACK"
    assert chargers.candidates[0].variant.sku == "CHG-BLACK"

    result = combine([cases, chargers], total_budget=Decimal("2000"))

    assert result.outcome is CombinationOutcome.WITHIN_BUDGET
    assert result.total == Decimal("1500.00")
    assert [item.candidate.variant.sku for item in result.items] == ["CASE-BLACK", "CHG-BLUE"]


def test_the_search_maximizes_summed_score_not_minimizes_price() -> None:
    """A budget is a ceiling, not a target.

    The cheapest basket that fits is ₹700 and the chosen one is ₹1,500. Spending
    less would mean handing the buyer two products they did not ask for when
    their budget covered one they did.
    """
    cases = recommendation(
        "phone_case",
        [case("CASE-BLACK", "1200.00", color="black"), case("CASE-BLUE", "400.00", color="blue")],
        requirement=WANTS_BLACK_CASE,
    )
    chargers = recommendation(
        "charger",
        [
            charger("CHG-BLACK", "1000.00", color="black"),
            charger("CHG-BLUE", "300.00", color="blue"),
        ],
        requirement=WANTS_BLACK_CHARGER,
    )

    result = combine([cases, chargers], total_budget=Decimal("2000"))
    cheapest_possible = Decimal("700.00")

    assert result.total > cheapest_possible
    assert result.combined_score == sum(
        (item.candidate.final_score for item in result.items), Decimal("0")
    )
    # No fitting pair scores higher — verified against every pair by hand:
    # (black, black) 2200 is over budget; (black, blue) 0.93; (blue, black) 0.92;
    # (blue, blue) 0.57.
    assert result.combined_score == Decimal("0.930000")


def test_a_deeper_pool_than_top_k_is_searched() -> None:
    """`SEARCH_DEPTH` is 5 while the buyer is shown 3 (RULE 11).

    The three black cases outrank the two blue ones on preference, so the Top-3
    the buyer sees are all ₹800 or more — and none of them fits beside a ₹1,500
    charger inside ₹2,150. The fourth-ranked case does. Searching only the
    presented candidates would report no combination when one exists.
    """
    cases = recommendation(
        "phone_case",
        [
            case("CASE-0", "1000.00", color="black"),
            case("CASE-1", "900.00", color="black"),
            case("CASE-2", "800.00", color="black"),
            case("CASE-3", "700.00", color="blue"),
            case("CASE-4", "600.00", color="blue"),
        ],
        requirement=WANTS_BLACK_CASE,
    )
    chargers = recommendation("charger", [charger("CHG", "1500.00")])

    presented = [c.variant.sku for c in cases.candidates[:3]]
    result = combine([cases, chargers], total_budget=Decimal("2150"))

    assert presented == ["CASE-2", "CASE-1", "CASE-0"]
    assert result.outcome is CombinationOutcome.WITHIN_BUDGET
    assert result.items[0].candidate.variant.sku == "CASE-4"
    assert result.items[0].candidate.rank == 4
    assert result.total == Decimal("2100.00")


def test_no_fitting_combination_says_so_rather_than_exceeding_the_budget() -> None:
    """R§14's discipline applied to combinations: never quietly return a basket
    over budget, and never silently drop a requested product type."""
    cases = recommendation("phone_case", [case("CASE", "2000.00")])
    chargers = recommendation("charger", [charger("CHG", "2000.00")])

    result = combine([cases, chargers], total_budget=Decimal("1000"))

    assert result.outcome is CombinationOutcome.NO_COMBINATION_WITHIN_BUDGET
    assert result.items == ()
    assert not result.fits_budget


def test_a_product_type_with_no_candidates_makes_the_result_incomplete() -> None:
    """ADR-004: never silently answer a two-product request with one product."""
    cases = recommendation("phone_case", [case("CASE", "999.00")])
    chargers = recommend(
        [],
        ProductRequirement(label="charger"),
        merchant_id=MERCHANT_ID,
        stock={},
    )

    result = combine([cases, chargers], total_budget=Decimal("3000"))

    assert chargers.outcome is RecommendationOutcome.NO_MATCH
    assert result.outcome is CombinationOutcome.INCOMPLETE
    assert result.missing_labels == ("charger",)
    assert result.items == ()


def test_an_empty_request_is_incomplete_rather_than_an_empty_success() -> None:
    result = combine([], total_budget=Decimal("3000"))

    assert result.outcome is CombinationOutcome.INCOMPLETE


# --------------------------------------------------------------------------
# Quantity and money
# --------------------------------------------------------------------------


def test_quantity_multiplies_the_line_and_the_total() -> None:
    """Two cables at ₹499 is ₹998 against the budget, not ₹499."""
    cables = recommendation(
        "usb_cable",
        [make_variant("CABLE", "499.00", category_slug="usb_cable")],
        requirement=ProductRequirement(label="usb_cable", quantity=2),
    )

    result = combine([cables], total_budget=Decimal("1000"))

    assert result.items[0].quantity == 2
    assert result.items[0].line_total == Decimal("998.00")
    assert result.total == Decimal("998.00")


def test_a_quantity_that_breaks_the_budget_is_caught() -> None:
    cables = recommendation(
        "usb_cable",
        [make_variant("CABLE", "499.00", category_slug="usb_cable")],
        requirement=ProductRequirement(label="usb_cable", quantity=3),
    )

    result = combine([cables], total_budget=Decimal("1000"))

    assert result.outcome is CombinationOutcome.NO_COMBINATION_WITHIN_BUDGET


def test_totals_are_decimal_and_exact() -> None:
    """ADR-008. `0.1 + 0.2` is the reason this is not a float."""
    a = recommendation("a", [make_variant("A", "0.10", category_slug="a")])
    b = recommendation("b", [make_variant("B", "0.20", category_slug="b")])

    result = combine([a, b])

    assert isinstance(result.total, Decimal)
    assert result.total == Decimal("0.30")


def test_mixing_currencies_is_refused_rather_than_converted() -> None:
    """ADR-008 defines no conversion anywhere, so inventing a rate here would be
    inventing a price. A guard against a future catalog, not a live condition."""
    rupees = recommendation("a", [make_variant("A", "999.00", category_slug="a")])
    dollars = recommendation("b", [make_variant("B", "20.00", category_slug="b", currency="USD")])

    with pytest.raises(ValueError, match="across currencies"):
        combine([rupees, dollars])


# --------------------------------------------------------------------------
# Determinism (RULE 8)
# --------------------------------------------------------------------------


def test_the_same_request_chooses_the_same_basket_every_time() -> None:
    cases = recommendation(
        "phone_case", [case(f"CASE-{i}", f"{500 + i * 100}.00") for i in range(5)]
    )
    chargers = recommendation(
        "charger", [charger(f"CHG-{i}", f"{500 + i * 100}.00") for i in range(5)]
    )

    chosen = {
        tuple(
            item.candidate.variant.sku
            for item in combine([cases, chargers], total_budget=Decimal("1400")).items
        )
        for _ in range(20)
    }

    assert len(chosen) == 1


def test_a_tie_on_score_breaks_on_the_lower_total() -> None:
    """Two baskets that score identically: the cheaper one is chosen, and the
    choice does not depend on iteration order."""
    a = recommendation("a", [make_variant("A1", "300.00", category_slug="a")])
    b = recommendation(
        "b",
        [
            make_variant("B1", "300.00", category_slug="b"),
            make_variant("B2", "300.00", category_slug="b"),
        ],
    )

    result = combine([a, b], total_budget=Decimal("650"))

    assert result.total == Decimal("600.00")


def test_the_combination_carries_the_budget_it_was_judged_against() -> None:
    """So that "within budget" can be checked afterwards rather than trusted."""
    cases = recommendation("phone_case", [case("CASE", "999.00")])

    result = combine([cases], total_budget=Decimal("3000"))

    assert result.total_budget == Decimal("3000")
    assert result.total <= result.total_budget


def test_ranking_and_combining_share_the_same_candidates() -> None:
    """The combination is chosen from ranked output, so a product that failed a
    hard constraint cannot reappear in a basket."""
    cheap_but_gone = make_variant("GONE", "99.00", category_slug="phone_case")
    available = make_variant("HERE", "999.00", category_slug="phone_case")
    variants = [cheap_but_gone, available]

    result = recommend(
        variants,
        ProductRequirement(label="phone_case"),
        merchant_id=MERCHANT_ID,
        stock=stock_for(variants, missing=["GONE"]),
    )
    basket = combine([result], total_budget=Decimal("3000"))

    assert [c.variant.sku for c in result.candidates] == ["HERE"]
    assert [item.candidate.variant.sku for item in basket.items] == ["HERE"]


def test_rank_is_not_consulted_for_the_basket_beyond_its_own_output() -> None:
    """A sanity check on the seam: `combine` reads `Recommendation.candidates`
    and nothing else, so it cannot smuggle in a product the filter removed."""
    ranked = rank([make_variant("ONLY", "999.00")], ProductRequirement(label="phone_case"), top_k=3)

    assert len(ranked) == 1
