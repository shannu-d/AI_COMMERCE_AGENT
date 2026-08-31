"""The reason label is derived, not written (RULE 10; ADR-004, open question A7).

The property under test throughout: every field of an `Explanation` is a
function of the arithmetic that produced the ordering. Nothing here consults a
model, and there is no field a model could fill.
"""

from __future__ import annotations

from decimal import Decimal
from itertools import pairwise

from app.domain import LABEL_TEXT, ProductRequirement, RecommendationLabel
from app.ranking import aggregate, get_profile, rank
from app.ranking.explain import explain
from tests.ranking.conftest import make_variant


def breakdown(*, preference: str, price: str, relevance: str, profile: str = "default"):
    return aggregate(
        get_profile(profile),
        preference=Decimal(preference),
        price=Decimal(price),
        relevance=Decimal(relevance),
    )


def test_rank_one_is_best_overall() -> None:
    """It won on the weighted total, which is the question that was asked."""
    result = explain(
        breakdown(preference="0.1", price="1.0", relevance="0.1"), rank=1, next_score=None
    )

    assert result.label is RecommendationLabel.BEST_OVERALL


def test_a_runner_up_carried_by_price_is_best_price() -> None:
    result = explain(
        breakdown(preference="0.0", price="1.0", relevance="0.0"), rank=2, next_score=None
    )

    assert result.label is RecommendationLabel.BEST_PRICE
    assert result.winning_component == "price"


def test_a_runner_up_carried_by_preference_is_a_closest_match() -> None:
    result = explain(
        breakdown(preference="1.0", price="0.0", relevance="0.0"), rank=2, next_score=None
    )

    assert result.label is RecommendationLabel.CLOSEST_MATCH
    assert result.winning_component == "preference"


def test_a_runner_up_carried_by_relevance_is_also_a_closest_match() -> None:
    """Preference, relevance and compatibility are all statements about fit, so
    they share a label; price is the one that is about money."""
    result = explain(
        breakdown(preference="0.0", price="0.0", relevance="1.0"), rank=3, next_score=None
    )

    assert result.label is RecommendationLabel.CLOSEST_MATCH


def test_the_winning_component_is_the_largest_contribution_not_the_largest_score() -> None:
    """A 1.0 on a 0.20 weight contributes less than a 0.6 on a 0.50 weight.

    Reporting the raw score instead would tell the buyer the ranking turned on
    something it did not.
    """
    result = breakdown(preference="0.6", price="0.0", relevance="1.0")

    assert result.winning_component.name == "preference"  # 0.30 vs 0.20


def test_the_margin_is_the_lead_over_the_next_candidate() -> None:
    """The number that answers "was this close?" without re-deriving the scores."""
    result = explain(
        breakdown(preference="1.0", price="1.0", relevance="1.0"),
        rank=1,
        next_score=Decimal("0.900000"),
    )

    assert result.margin == Decimal("0.100000")


def test_the_last_candidate_has_no_margin() -> None:
    """`None`, not zero: it has nothing to lead, which is not the same as leading
    by nothing."""
    result = explain(
        breakdown(preference="1.0", price="1.0", relevance="1.0"), rank=3, next_score=None
    )

    assert result.margin is None


def test_margins_are_computed_across_a_real_ranking() -> None:
    candidates = [
        make_variant("A", "500.00", attributes={"color": "black"}),
        make_variant("B", "1000.00", attributes={"color": "black"}),
        make_variant("C", "1500.00", attributes={"color": "blue"}),
    ]
    requirement = ProductRequirement(
        label="phone_case", max_price=Decimal("1500"), preferences={"color": "black"}
    )

    ranked = rank(candidates, requirement, top_k=3)

    for leader, follower in pairwise(ranked):
        assert leader.explanation.margin == leader.final_score - follower.final_score
    assert ranked[-1].explanation.margin is None


def test_every_label_has_display_text() -> None:
    """The structured field is authoritative; the text is what the frontend
    renders and what the model may paraphrase."""
    for label in RecommendationLabel:
        assert LABEL_TEXT[label]


def test_the_label_text_matches_adr_004() -> None:
    assert LABEL_TEXT[RecommendationLabel.BEST_OVERALL] == "Best overall"
    assert LABEL_TEXT[RecommendationLabel.BEST_PRICE] == "Best price"
    assert LABEL_TEXT[RecommendationLabel.CLOSEST_MATCH] == "Closest match to your requirements"


def test_there_are_exactly_three_labels() -> None:
    """A closed enum. A free-text reason field is what would let the model write
    an ungrounded claim about a computation it did not perform."""
    assert len(RecommendationLabel) == 3


def test_explaining_the_same_score_twice_gives_the_same_answer() -> None:
    """RULE 8 applies to the explanation as much as to the ordering."""
    score = breakdown(preference="0.5", price="0.5", relevance="0.5")

    first = explain(score, rank=2, next_score=Decimal("0.4"))
    second = explain(score, rank=2, next_score=Decimal("0.4"))

    assert first == second
