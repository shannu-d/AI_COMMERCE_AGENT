"""Ranking weight profiles — configuration, not code (R§17 RULE 14).

> The initial ranking weights are configurable implementation parameters, not
> permanent business truths. (RULE 14)

So every weight in the system is declared here, as data, and nowhere else. No
scorer, aggregator or service contains a numeric weight; they are handed a
`WeightProfile` and multiply by what it says.

`architecture.md` gives **two** weight sets for the same calculation:

* R§4 — Compatibility 0.40 / Preference 0.30 / Price 0.20 / Relevance 0.10;
* R§19 — Preference 0.50 / Price 0.30 / Relevance 0.20, *after* compatibility
  has been applied as a hard filter, and it says that approach is preferred.

ADR-004 resolves this: `default` is the R§19 three-weight set, and the R§4
four-weight set survives as `explainability_demo` so the specification's other
presentation stays runnable and its worked example (R§10) stays reproducible.
`explainability_demo` is never used for a real recommendation — it exists to
demonstrate the arithmetic, and even under it no incompatible product reaches
the scorer, because compatibility is filtered first either way (ADR-005).

`price_sensitive` and `premium` are the profiles R§12 asks for ("I want the
cheapest compatible case" / "I want a premium case, price doesn't matter").
ADR-004 names them without fixing their numbers; the numbers are chosen here and
recorded in `docs/notes/deviations.md`. The model may select a profile **by
name**; it must never emit a numeric weight (ADR-004).
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

__all__ = [
    "DEFAULT_PROFILE_NAME",
    "PROFILES",
    "PROFILE_NAMES",
    "UnknownWeightProfileError",
    "WeightProfile",
    "get_profile",
]


class UnknownWeightProfileError(ValueError):
    """Raised for a profile name that does not exist.

    Loudly, rather than falling back to `default`: a typo in configuration that
    silently changes how products are ordered is exactly the class of bug RULE 8
    (determinism) and RULE 14 (configurability) exist to prevent.
    """


@dataclass(frozen=True, slots=True)
class WeightProfile:
    """One named set of weights, validated at construction.

    The weights must sum to exactly 1.0 (R§19: ``W_pref + W_price + W_rel = 1``)
    so that `FinalScore` stays inside [0, 1] and remains comparable across
    profiles. `Decimal`, not `float`, so the sum is exact and the resulting
    scores do not depend on binary floating-point noise (ADR-004).
    """

    name: str
    preference: Decimal
    price: Decimal
    relevance: Decimal
    #: Non-zero only where compatibility is retained as an explicit scoring
    #: dimension for explainability. Under every operational profile it is 0.0
    #: and incompatible products never reach the scorer at all (ADR-005).
    compatibility: Decimal = Decimal("0")
    description: str = ""

    def __post_init__(self) -> None:
        weights = (self.preference, self.price, self.relevance, self.compatibility)
        if any(weight < 0 for weight in weights):
            raise ValueError(f"weight profile {self.name!r} has a negative weight")
        total = sum(weights, Decimal("0"))
        if total != Decimal("1"):
            raise ValueError(
                f"weight profile {self.name!r} sums to {total}, not 1 "
                "(R§19: W_pref + W_price + W_rel = 1)"
            )

    @property
    def scores_compatibility(self) -> bool:
        """Whether this profile emits a compatibility component at all."""
        return self.compatibility > 0


#: Every profile the application will run. Adding one is a configuration change.
PROFILES: dict[str, WeightProfile] = {
    profile.name: profile
    for profile in (
        WeightProfile(
            name="default",
            preference=Decimal("0.50"),
            price=Decimal("0.30"),
            relevance=Decimal("0.20"),
            description=(
                "R§19's preferred weighting, applied after compatibility and "
                "inventory have already eliminated candidates."
            ),
        ),
        WeightProfile(
            name="price_sensitive",
            preference=Decimal("0.20"),
            price=Decimal("0.60"),
            relevance=Decimal("0.20"),
            description=(
                'R§12 example 1 — "I want the cheapest compatible case": price '
                "importance HIGH, other preferences LOW. Compatibility stays a "
                "hard constraint, so cheapness still cannot buy its way past it."
            ),
        ),
        WeightProfile(
            name="premium",
            preference=Decimal("0.70"),
            price=Decimal("0.10"),
            relevance=Decimal("0.20"),
            description=(
                'R§12 example 2 — "price doesn\'t matter": stated preferences '
                "dominate. Price is de-weighted, never inverted: rewarding a "
                "higher price would be an invented claim that dear means good."
            ),
        ),
        WeightProfile(
            name="explainability_demo",
            preference=Decimal("0.30"),
            price=Decimal("0.20"),
            relevance=Decimal("0.10"),
            compatibility=Decimal("0.40"),
            description=(
                "R§4's four-weight presentation, kept runnable so the R§10 "
                "worked example reproduces. Not for real recommendations."
            ),
        ),
    )
}

DEFAULT_PROFILE_NAME = "default"

#: Sorted, so the tool schema that offers these to the model is stable.
PROFILE_NAMES: tuple[str, ...] = tuple(sorted(PROFILES))


def get_profile(name: str | None = None) -> WeightProfile:
    """Look up a profile by name. `None` yields the default."""
    if name is None:
        name = DEFAULT_PROFILE_NAME
    try:
        return PROFILES[name]
    except KeyError:
        raise UnknownWeightProfileError(
            f"unknown ranking weight profile {name!r}; known profiles: {', '.join(PROFILE_NAMES)}"
        ) from None
