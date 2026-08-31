"""The aggregator: hard filter, score, weight, sort, Top-K (R§16, ADR-004).

    filter (ADR-005)  ->  four feature scores  ->  weighted sum  ->  sort  ->  Top-K

Everything here is pure. It takes domain values and returns domain values, and
it neither opens a session nor knows that PostgreSQL exists. That is what makes
the R§10 worked example reproducible as a unit test, and it is the property
ADR-004 asks for: *"a ranker that is unit-testable without a database and
without a model; scores that can be recomputed by hand"*.

The model appears nowhere in this file, by construction. R§11 forbids it from
computing the score; ADR-001 forbids this side of the boundary from importing
it at all.
"""

from __future__ import annotations

import uuid
from collections.abc import Collection, Iterable, Mapping
from dataclasses import replace
from decimal import Decimal

from app.domain import (
    FilterResult,
    HardConstraint,
    ProductRequirement,
    RankedCandidate,
    Recommendation,
    RecommendationOutcome,
    RejectedCandidate,
    ScoreBreakdown,
    StockStatus,
    StockView,
    VariantView,
    WeightedComponent,
)
from app.ranking.explain import explain
from app.ranking.filters import apply_hard_constraints
from app.ranking.scorers import (
    ZERO,
    compatibility_score,
    preference_score,
    price_denominator,
    price_score,
    quantize_score,
    relevance_score,
)
from app.ranking.weights import WeightProfile, get_profile

__all__ = ["DEFAULT_TOP_K", "aggregate", "rank", "recommend", "score_variant"]

#: R§17 RULE 11: "a small number of strong candidates, preferably Top 3".
DEFAULT_TOP_K = 3


def aggregate(
    profile: WeightProfile,
    *,
    preference: Decimal,
    price: Decimal,
    relevance: Decimal,
    compatibility: Decimal | None = None,
) -> ScoreBreakdown:
    """The weighted sum, and nothing else. R§19::

        FinalScore(p) = W_pref x PreferenceScore(p)
                      + W_price x PriceScore(p)
                      + W_rel  x RelevanceScore(p)

    plus `W_compat x CompatibilityScore(p)` under a profile that scores
    compatibility (R§4's four-weight presentation).

    Component order is fixed — compatibility, preference, price, relevance — so
    that a tie on contribution resolves the same way every time (RULE 8). It is
    the order `architecture.md` itself lists them in.

    This function is the M3 exit test: fed the feature scores R§10 states, under
    the `explainability_demo` profile, it must return 0.7968 and 0.7868.
    """
    components: list[WeightedComponent] = []
    if profile.scores_compatibility:
        components.append(
            WeightedComponent(
                name="compatibility",
                score=compatibility if compatibility is not None else ZERO,
                weight=profile.compatibility,
            )
        )
    components.extend(
        (
            WeightedComponent(name="preference", score=preference, weight=profile.preference),
            WeightedComponent(name="price", score=price, weight=profile.price),
            WeightedComponent(name="relevance", score=relevance, weight=profile.relevance),
        )
    )
    total = sum((component.contribution for component in components), ZERO)
    return ScoreBreakdown(
        profile_name=profile.name,
        components=tuple(components),
        final_score=quantize_score(total),
    )


def score_variant(
    variant: VariantView,
    requirement: ProductRequirement,
    *,
    profile: WeightProfile,
    denominator: Decimal | None,
    is_compatible: bool = True,
) -> ScoreBreakdown:
    """Compute all four feature scores for one variant, then aggregate them.

    `is_compatible` is `True` for every candidate that reaches here, because
    incompatible ones were removed by the filter. It is a parameter rather than
    a literal so that the property is asserted by a test instead of assumed by a
    reader.
    """
    return aggregate(
        profile,
        preference=preference_score(variant, requirement.preferences),
        price=price_score(variant.price, denominator),
        relevance=relevance_score(variant, requirement),
        compatibility=compatibility_score(is_compatible),
    )


def _sort_key(candidate: tuple[VariantView, ScoreBreakdown]) -> tuple[Decimal, Decimal, str]:
    """Highest score, then lower price, then SKU ascending (ADR-004).

    Three keys because two are not enough: scores tie often at six decimal
    places on a small catalog, and price ties whenever a product has several
    colours at one price. SKU is unique per merchant, so the order is total —
    which is what RULE 8 requires. An unstable sort would make the same request
    return two different orderings.
    """
    variant, breakdown = candidate
    return (-breakdown.final_score, variant.price, variant.sku)


def rank(
    candidates: Iterable[VariantView],
    requirement: ProductRequirement,
    *,
    profile: WeightProfile | str | None = None,
    top_k: int = DEFAULT_TOP_K,
    stock: Mapping[uuid.UUID, StockView] | None = None,
) -> tuple[RankedCandidate, ...]:
    """Score, order and cut an already-filtered candidate set.

    Candidates must have passed `apply_hard_constraints` — this does no
    filtering and will happily rank whatever it is handed. `recommend` is the
    entry point that does both; this one exists separately so the ordering can
    be tested without constructing constraints.
    """
    profile = profile if isinstance(profile, WeightProfile) else get_profile(profile)
    candidates = list(candidates)
    denominator = price_denominator(candidates, requirement.max_price)

    scored = [
        (variant, score_variant(variant, requirement, profile=profile, denominator=denominator))
        for variant in candidates
    ]
    scored.sort(key=_sort_key)
    selected = scored[:top_k] if top_k >= 0 else scored

    ranked: list[RankedCandidate] = []
    for position, (variant, breakdown) in enumerate(selected, start=1):
        following = selected[position][1].final_score if position < len(selected) else None
        stock_view = stock.get(variant.id) if stock else None
        ranked.append(
            RankedCandidate(
                rank=position,
                variant=variant,
                score=breakdown,
                explanation=explain(breakdown, rank=position, next_score=following),
                stock_status=stock_view.status if stock_view else StockStatus.NO_RECORD,
            )
        )
    return tuple(ranked)


def _alternatives(
    rejected: tuple[RejectedCandidate, ...],
    requirement: ProductRequirement,
    *,
    profile: WeightProfile,
    top_k: int,
    stock: Mapping[uuid.UUID, StockView],
) -> tuple[tuple[RankedCandidate, ...], tuple[HardConstraint, ...]]:
    """Real catalog products that failed only a relaxable constraint (R§14).

    Two rules govern this, and both are safety rules rather than preferences:

    * only `BUDGET` and `REQUIRED_SPECIFICATION` are relaxable. Compatibility
      never is — a case for a different phone is a wrong answer, not a lesser
      one. Inventory never is, because RULE 5 forbids presenting an
      out-of-stock product as purchasable and an alternative nobody can buy is
      not an alternative. Category never is: a charger is not a cheaper case.
    * the alternatives are scored with the budget removed. Keeping the buyer's
      budget as the price denominator would score an over-budget product below
      zero, which the clamp would flatten to a meaningless tie. With the budget
      relaxed there is no budget, so the candidate-set denominator applies —
      the same rule any unbudgeted request uses.

    The constraints that were relaxed are returned alongside, so the agent can
    say *which* one the product does not meet rather than presenting it as a
    match.
    """
    relaxable = [candidate for candidate in rejected if candidate.is_relaxable]
    if not relaxable:
        return (), ()

    relaxed_requirement = replace(requirement, max_price=None, required_attributes={})
    ranked = rank(
        [candidate.variant for candidate in relaxable],
        relaxed_requirement,
        profile=profile,
        top_k=top_k,
        stock=stock,
    )
    offered = {candidate.variant.id for candidate in ranked}
    relaxed = {
        constraint
        for candidate in relaxable
        if candidate.variant.id in offered
        for constraint in candidate.constraints
    }
    # Enum member order, so the payload is stable across runs.
    ordered = tuple(constraint for constraint in HardConstraint if constraint in relaxed)
    return ranked, ordered


def recommend(
    candidates: Iterable[VariantView],
    requirement: ProductRequirement,
    *,
    merchant_id: uuid.UUID,
    stock: Mapping[uuid.UUID, StockView],
    compatible_product_ids: Collection[uuid.UUID] | None = None,
    profile: WeightProfile | str | None = None,
    top_k: int = DEFAULT_TOP_K,
) -> Recommendation:
    """Filter, rank and classify — the whole pure pipeline for one requirement.

    The outcome is one of three, and the distinction is the point (ADR-005,
    R§14). `EXACT_MATCH` means every hard constraint was satisfied.
    `NO_MATCH_WITH_ALTERNATIVES` means nothing was, but real catalog products
    satisfied everything except a named relaxable constraint — they are returned
    in a *separate field*, so nothing downstream can mistake one for a match.
    `NO_MATCH` means the honest answer is that there is nothing, which R§14
    requires be said rather than papered over with a fabricated product, a
    relaxed compatibility rule or an invented availability.
    """
    profile = profile if isinstance(profile, WeightProfile) else get_profile(profile)
    filtered: FilterResult = apply_hard_constraints(
        candidates,
        requirement,
        merchant_id=merchant_id,
        stock=stock,
        compatible_product_ids=compatible_product_ids,
    )

    if filtered.survivors:
        return Recommendation(
            requirement=requirement,
            outcome=RecommendationOutcome.EXACT_MATCH,
            profile_name=profile.name,
            candidates=rank(
                filtered.survivors, requirement, profile=profile, top_k=top_k, stock=stock
            ),
            rejected=filtered.rejected,
        )

    alternatives, relaxed = _alternatives(
        filtered.rejected, requirement, profile=profile, top_k=top_k, stock=stock
    )
    return Recommendation(
        requirement=requirement,
        outcome=(
            RecommendationOutcome.NO_MATCH_WITH_ALTERNATIVES
            if alternatives
            else RecommendationOutcome.NO_MATCH
        ),
        profile_name=profile.name,
        alternatives=alternatives,
        relaxed_constraints=relaxed,
        rejected=filtered.rejected,
    )
