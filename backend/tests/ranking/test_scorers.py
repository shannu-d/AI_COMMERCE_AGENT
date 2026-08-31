"""The four feature scorers, against the specification's own worked numbers.

Where `architecture.md` gives an example with an arithmetic result — R§7's
1.0 / 0.5 / 0.0, R§8's 0.67 and 0.33, R§10's 0.334 and 0.134 — the example is
the test. Where it gives no formula at all (R§9's relevance) the assertions are
against ADR-004, and say so.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.domain import ProductRequirement
from app.ranking.scorers import (
    attribute_match,
    category_match,
    compatibility_score,
    preference_score,
    price_denominator,
    price_score,
    quantize_score,
    relevance_score,
    tag_match,
    text_match,
)
from tests.ranking.conftest import make_variant

# --------------------------------------------------------------------------
# R§7 — PreferenceScore
# --------------------------------------------------------------------------

PREFERENCES = {"color": "black", "material": "leather"}


def test_r7_product_a_matches_both_preferences() -> None:
    """The specification's Product A: color=black, material=leather -> 2/2 = 1.0."""
    variant = make_variant(
        "A", "999.00", attributes={"color": "black"}, product_attributes={"material": "leather"}
    )

    assert preference_score(variant, PREFERENCES) == Decimal("1.000000")


def test_r7_product_b_matches_one_of_two() -> None:
    """Product B: color=black, material=TPU -> 1/2 = 0.5."""
    variant = make_variant(
        "B", "999.00", attributes={"color": "black"}, product_attributes={"material": "TPU"}
    )

    assert preference_score(variant, PREFERENCES) == Decimal("0.500000")


def test_r7_product_c_matches_neither() -> None:
    """Product C: color=blue, material=TPU -> 0/2 = 0.0."""
    variant = make_variant(
        "C", "999.00", attributes={"color": "blue"}, product_attributes={"material": "TPU"}
    )

    assert preference_score(variant, PREFERENCES) == Decimal("0.000000")


def test_preferences_are_matched_against_merged_attributes() -> None:
    """D§27: the variant's own attributes win over its product's.

    "Black leather case" is one preference about the variant and one about the
    product; a scorer looking at only one level would score it 0.5 at best.
    """
    variant = make_variant(
        "M",
        "999.00",
        attributes={"color": "black"},
        product_attributes={"color": "blue", "material": "leather"},
    )

    assert preference_score(variant, PREFERENCES) == Decimal("1.000000")


def test_no_stated_preferences_scores_zero_not_one() -> None:
    """ADR-004 (open question A4), decided against the analysis proposal.

    "The buyer stated no preferences" is not evidence that every product matches
    them. The term becomes a constant, so ordering is untouched — only the
    absolute score is lower.
    """
    variant = make_variant("N", "999.00", attributes={"color": "black"})

    assert preference_score(variant, {}) == Decimal("0")


def test_preference_matching_is_case_insensitive_for_strings() -> None:
    variant = make_variant("U", "999.00", attributes={"color": "BLACK"})

    assert preference_score(variant, {"color": "black"}) == Decimal("1.000000")


def test_a_missing_attribute_does_not_match() -> None:
    variant = make_variant("X", "999.00", attributes={})

    assert preference_score(variant, {"color": "black"}) == Decimal("0.000000")


# --------------------------------------------------------------------------
# R§8 — PriceScore
# --------------------------------------------------------------------------


def test_r8_worked_example() -> None:
    """Budget ₹1,500: ₹500 -> 0.67, ₹1,000 -> 0.33."""
    assert price_score(Decimal("500"), Decimal("1500")).quantize(Decimal("0.01")) == Decimal("0.67")
    assert price_score(Decimal("1000"), Decimal("1500")).quantize(Decimal("0.01")) == Decimal(
        "0.33"
    )


def test_r10_worked_example_price_scores() -> None:
    """₹999 -> 0.334 and ₹1,299 -> 0.134 against a ₹1,500 budget."""
    assert price_score(Decimal("999.00"), Decimal("1500")) == Decimal("0.334000")
    assert price_score(Decimal("1299.00"), Decimal("1500")) == Decimal("0.134000")


def test_cheaper_is_always_better() -> None:
    cheap = price_score(Decimal("499"), Decimal("1500"))
    dear = price_score(Decimal("1499"), Decimal("1500"))

    assert cheap > dear


def test_a_stated_budget_is_the_denominator() -> None:
    candidates = [make_variant("A", "999.00"), make_variant("B", "1299.00")]

    assert price_denominator(candidates, Decimal("1500")) == Decimal("1500")


def test_without_a_budget_the_most_expensive_candidate_is_the_denominator() -> None:
    """ADR-004: deterministic within a request, meaningless across two."""
    candidates = [make_variant("A", "999.00"), make_variant("B", "1299.00")]

    assert price_denominator(candidates, None) == Decimal("1299.00")


@pytest.mark.parametrize(
    ("prices", "reason"),
    [
        ([], "an empty candidate set"),
        (["999.00"], "a single candidate"),
        (["999.00", "999.00"], "every candidate at one price"),
        (["0.00", "0.00"], "a maximum price of zero"),
    ],
)
def test_degenerate_candidate_sets_have_no_denominator(prices: list[str], reason: str) -> None:
    """ADR-004, closing open question A3.

    In each of these the ratio carries no ordering information, and in the last
    it does not exist at all. The alternative — dividing anyway — ranks a lone
    candidate at 0.0, which reads as "bad price" when nothing was compared.
    """
    candidates = [make_variant(f"SKU{i}", price) for i, price in enumerate(prices)]

    assert price_denominator(candidates, None) is None, reason


def test_no_denominator_scores_one() -> None:
    assert price_score(Decimal("999.00"), None) == Decimal("1")


def test_a_product_priced_exactly_at_the_budget_scores_zero() -> None:
    """R§8's own formula, kept. The product is still returned and still ranked;
    it simply earns nothing on price attractiveness, which is true."""
    assert price_score(Decimal("1500"), Decimal("1500")) == Decimal("0.000000")


# --------------------------------------------------------------------------
# R§9 — RelevanceScore (no formula in the specification; ADR-004 supplies one)
# --------------------------------------------------------------------------


def test_relevance_is_the_adr_004_weighted_sum() -> None:
    """0.40 category + 0.30 attribute + 0.20 text + 0.10 tag, all terms at 1.0."""
    variant = make_variant(
        "R",
        "999.00",
        product_name="Slim Case",
        category_slug="phone_case",
        attributes={"color": "black"},
        tags=("slim",),
    )
    requirement = ProductRequirement(
        label="phone_case",
        category_slug="phone_case",
        query_text="slim case black",
        preferences={"color": "black"},
    )

    # category 1.0, attribute 1/1, text 2/3 ("slim","case" of "slim","case","black"),
    # tag 1/1  ->  0.40 + 0.30 + 0.20*(2/3) + 0.10
    assert relevance_score(variant, requirement) == Decimal("0.933333")


def test_category_match_is_binary() -> None:
    variant = make_variant("C1", "999.00", category_slug="phone_case")

    assert category_match(variant, "phone_case") == Decimal("1")
    assert category_match(variant, "charger") == Decimal("0")


def test_category_match_without_a_requested_category_is_zero() -> None:
    """Silence is not a match. The term is then constant, so ordering is unaffected."""
    variant = make_variant("C2", "999.00")

    assert category_match(variant, None) == Decimal("0")


def test_attribute_match_counts_requirements_and_preferences_together() -> None:
    """ADR-004 says "the attributes the buyer explicitly requested".

    Requirements alone would be a dead term: every survivor was filtered on
    them, so it would be 1.0 for all of them and could reorder nothing.
    """
    variant = make_variant(
        "A1", "999.00", attributes={"color": "black"}, product_attributes={"material": "TPU"}
    )
    requirement = ProductRequirement(
        label="x", required_attributes={"material": "TPU"}, preferences={"color": "blue"}
    )

    assert attribute_match(variant, requirement.stated_attributes) == Decimal("0.5")


def test_text_match_is_query_token_overlap_over_name_and_description() -> None:
    variant = make_variant(
        "T1",
        "999.00",
        product_name="AeroCase Pro",
        product_description="Slim protective case for compatible smartphones.",
    )

    # "slim","case" both appear; "leather" does not -> 2/3
    assert text_match(variant, "slim leather case") == Decimal(2) / Decimal(3)


def test_text_match_without_a_query_is_zero() -> None:
    variant = make_variant("T2", "999.00", product_name="AeroCase Pro")

    assert text_match(variant, None) == Decimal("0")
    assert text_match(variant, "   ") == Decimal("0")


def test_text_match_denominator_is_the_query_so_a_chatty_query_cannot_reorder() -> None:
    """The dilution is identical for every candidate, so only absolute scores move."""
    a = make_variant("T3", "999.00", product_name="Slim Case")
    b = make_variant("T4", "999.00", product_name="Rugged Case")
    short, long = "slim case", "i would like a slim case please"

    assert text_match(a, short) > text_match(b, short)
    assert text_match(a, long) > text_match(b, long)


def test_tag_match_is_over_the_products_tags() -> None:
    """|query ∩ tags| / |tags| — a product mostly about what was asked for wins."""
    focused = make_variant("G1", "999.00", tags=("slim", "iphone"))
    scattergun = make_variant("G2", "999.00", tags=("slim", "iphone", "leather", "folio"))

    assert tag_match(focused, "slim iphone") == Decimal("1")
    assert tag_match(scattergun, "slim iphone") == Decimal("0.5")


def test_a_multiword_tag_matches_when_all_its_tokens_are_in_the_query() -> None:
    """Otherwise `fast_charging` could never match "fast charging" and the term
    would be dead for most of the catalog."""
    variant = make_variant("G3", "999.00", tags=("fast_charging",))

    assert tag_match(variant, "fast charging charger") == Decimal("1")
    assert tag_match(variant, "fast charger") == Decimal("0")


def test_a_product_with_no_tags_scores_zero_rather_than_dividing_by_zero() -> None:
    variant = make_variant("G4", "999.00", tags=())

    assert tag_match(variant, "slim") == Decimal("0")


# --------------------------------------------------------------------------
# R§6 — CompatibilityScore
# --------------------------------------------------------------------------


def test_compatibility_is_binary() -> None:
    assert compatibility_score(True) == Decimal("1")
    assert compatibility_score(False) == Decimal("0")


# --------------------------------------------------------------------------
# Precision
# --------------------------------------------------------------------------


def test_scores_are_quantized_so_ordering_never_depends_on_noise() -> None:
    """RULE 8. Two candidates separated only by representation would otherwise
    sort by it, and the sort would not survive a refactor."""
    assert quantize_score(Decimal("0.3333333333")) == Decimal("0.333333")
    assert quantize_score(Decimal("0.1234565")) == Decimal("0.123456")  # banker's rounding


def test_scores_are_clamped_to_the_unit_interval() -> None:
    """A guard, not arithmetic: every formula is already bounded, so a value
    outside means a bug, and 1.4 silently outranking everything is a worse way
    to discover it."""
    assert quantize_score(Decimal("1.4")) == Decimal("1.000000")
    assert quantize_score(Decimal("-0.4")) == Decimal("0.000000")


def test_no_scorer_returns_a_float() -> None:
    """ADR-008 keeps money in `Decimal`; ADR-004 keeps scores there for the same
    reason — a float total is not reproducible across platforms."""
    variant = make_variant("F", "999.00", attributes={"color": "black"}, tags=("slim",))
    requirement = ProductRequirement(label="x", category_slug="phone_case", query_text="slim")

    for value in (
        preference_score(variant, {"color": "black"}),
        price_score(variant.price, Decimal("1500")),
        relevance_score(variant, requirement),
        compatibility_score(True),
    ):
        assert isinstance(value, Decimal)
