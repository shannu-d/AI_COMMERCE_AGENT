"""Weight profiles are configuration, and configuration is validated (RULE 14)."""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.ranking.weights import (
    DEFAULT_PROFILE_NAME,
    PROFILE_NAMES,
    PROFILES,
    UnknownWeightProfileError,
    WeightProfile,
    get_profile,
)


@pytest.mark.parametrize("name", PROFILE_NAMES)
def test_every_profile_sums_to_exactly_one(name: str) -> None:
    """R§19: `W_pref + W_price + W_rel = 1`.

    Exactly one, in `Decimal`. A profile summing to 0.9999999 would still rank,
    which is what makes the bug worth a test: scores would silently compress and
    no output would look wrong.
    """
    profile = PROFILES[name]
    total = profile.preference + profile.price + profile.relevance + profile.compatibility

    assert total == Decimal("1")


def test_a_profile_that_does_not_sum_to_one_cannot_be_constructed() -> None:
    with pytest.raises(ValueError, match="sums to"):
        WeightProfile(
            name="broken",
            preference=Decimal("0.5"),
            price=Decimal("0.3"),
            relevance=Decimal("0.3"),
        )


def test_a_negative_weight_cannot_be_constructed() -> None:
    """A negative weight would make a *better* feature score lower the total."""
    with pytest.raises(ValueError, match="negative weight"):
        WeightProfile(
            name="inverted",
            preference=Decimal("1.2"),
            price=Decimal("-0.2"),
            relevance=Decimal("0"),
        )


def test_the_default_profile_is_the_three_weight_set_r19_prefers() -> None:
    """R§19 states the hard-filter approach is preferred; ADR-004 adopts it."""
    profile = get_profile()

    assert profile.name == DEFAULT_PROFILE_NAME
    assert (profile.preference, profile.price, profile.relevance) == (
        Decimal("0.50"),
        Decimal("0.30"),
        Decimal("0.20"),
    )
    assert profile.compatibility == Decimal("0")
    assert not profile.scores_compatibility


def test_only_the_demo_profile_scores_compatibility() -> None:
    """R§6: the 0.40 compatibility weight is "primarily a conceptual representation".

    Under every operational profile the weight is zero, because incompatible
    products are removed before scoring rather than allowed to compete
    (ADR-005). Keeping R§4's presentation runnable must not quietly make it the
    way recommendations are produced.
    """
    scoring = {name for name, p in PROFILES.items() if p.scores_compatibility}

    assert scoring == {"explainability_demo"}


def test_the_demo_profile_is_r4_verbatim() -> None:
    profile = get_profile("explainability_demo")

    assert (profile.compatibility, profile.preference, profile.price, profile.relevance) == (
        Decimal("0.40"),
        Decimal("0.30"),
        Decimal("0.20"),
        Decimal("0.10"),
    )


def test_r12_intents_have_a_profile_each() -> None:
    """R§12's two named intents — "cheapest" and "premium" — are selectable."""
    assert get_profile("price_sensitive").price > get_profile().price
    assert get_profile("premium").price < get_profile().price
    assert get_profile("premium").preference > get_profile().preference


def test_an_unknown_profile_fails_loudly_rather_than_falling_back() -> None:
    """Falling back to the default would silently change every ordering."""
    with pytest.raises(UnknownWeightProfileError, match="known profiles"):
        get_profile("cheapest_please")


def test_profiles_are_immutable() -> None:
    """RULE 8: nothing may retune the weights at request time."""
    profile = get_profile()

    with pytest.raises(AttributeError):
        profile.price = Decimal("0.9")  # type: ignore[misc]


def test_profile_names_are_sorted_so_a_tool_schema_is_stable() -> None:
    assert PROFILE_NAMES == tuple(sorted(PROFILES))
