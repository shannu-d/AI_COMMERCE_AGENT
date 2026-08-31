"""Multi-product requests against one overall budget (R§13, ADR-004).

    "I have an iPhone 16. I need a case and fast charger under ₹3,000."

Each product type has already been filtered and ranked on its own — R§13 runs a
separate pipeline per type, and every hard constraint including the per-item
budget has already been applied. What is left is the one question a per-type
ranking cannot answer: which *combination* fits the total.

The rule ADR-004 fixes (closing open question A5):

1. take the best candidate of each type; if the total fits, done — this is the
   overwhelmingly common case and it costs nothing;
2. otherwise search the top `SEARCH_DEPTH` of each type exhaustively for the
   combination that maximizes summed `FinalScore` subject to the budget. Three
   types at five candidates each is 125 combinations, so exhaustive is both
   affordable and exact, and being exact means being reproducible;
3. if nothing fits, say so. Never silently drop a requested product type, and
   never quietly return a combination over budget.

The result is a proposal, not a cart. Nothing here reserves stock, computes an
authoritative total for payment, or touches money that will move — the cart owns
that from M7, and the Policy Engine re-reads price and stock live before an
order exists (RULE 12, ADR-011).
"""

from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal
from itertools import product as cartesian_product

from app.domain import (
    CombinationItem,
    CombinationOutcome,
    ProductCombination,
    RankedCandidate,
    Recommendation,
)

__all__ = ["SEARCH_DEPTH", "combine"]

#: How many candidates per product type the exhaustive search considers
#: (ADR-004). Five is deeper than the Top-3 that is shown to the buyer, so the
#: search can reach past the presented candidates to find a fitting combination.
SEARCH_DEPTH = 5

ZERO = Decimal("0")


def combine(
    recommendations: Sequence[Recommendation],
    *,
    total_budget: Decimal | None = None,
    search_depth: int = SEARCH_DEPTH,
) -> ProductCombination:
    """Choose one candidate per requirement, within `total_budget` if stated."""
    missing = tuple(
        recommendation.requirement.label
        for recommendation in recommendations
        if not recommendation.candidates
    )
    if missing or not recommendations:
        return ProductCombination(
            outcome=CombinationOutcome.INCOMPLETE,
            total_budget=total_budget,
            missing_labels=missing,
        )

    currency = _single_currency(recommendations)

    best_of_each = tuple(
        _item(recommendation, recommendation.candidates[0]) for recommendation in recommendations
    )
    if total_budget is None or _total(best_of_each) <= total_budget:
        return _combination(best_of_each, currency, total_budget)

    chosen = _search(recommendations, total_budget, search_depth)
    if chosen is None:
        return ProductCombination(
            outcome=CombinationOutcome.NO_COMBINATION_WITHIN_BUDGET,
            currency=currency,
            total_budget=total_budget,
        )
    return _combination(chosen, currency, total_budget)


def _search(
    recommendations: Sequence[Recommendation],
    total_budget: Decimal,
    search_depth: int,
) -> tuple[CombinationItem, ...] | None:
    """Exhaustive search for the highest-scoring combination that fits.

    Ties are broken by lower total, then by the SKUs in requirement order, so
    two runs over the same catalog always choose the same basket (RULE 8).
    """
    pools = [
        [_item(recommendation, candidate) for candidate in recommendation.candidates[:search_depth]]
        for recommendation in recommendations
    ]

    best: tuple[tuple[Decimal, Decimal, tuple[str, ...]], tuple[CombinationItem, ...]] | None = None
    for combination in cartesian_product(*pools):
        total = _total(combination)
        if total > total_budget:
            continue
        skus = tuple(item.candidate.variant.sku for item in combination)
        key = (-_score(combination), total, skus)
        if best is None or key < best[0]:
            best = (key, combination)
    return best[1] if best else None


def _item(recommendation: Recommendation, candidate: RankedCandidate) -> CombinationItem:
    return CombinationItem(
        label=recommendation.requirement.label,
        candidate=candidate,
        quantity=recommendation.requirement.quantity,
    )


def _total(items: Sequence[CombinationItem]) -> Decimal:
    return sum((item.line_total for item in items), ZERO)


def _score(items: Sequence[CombinationItem]) -> Decimal:
    return sum((item.candidate.final_score for item in items), ZERO)


def _combination(
    items: tuple[CombinationItem, ...], currency: str, total_budget: Decimal | None
) -> ProductCombination:
    return ProductCombination(
        outcome=CombinationOutcome.WITHIN_BUDGET,
        items=items,
        total=_total(items),
        currency=currency,
        total_budget=total_budget,
        combined_score=_score(items),
    )


def _single_currency(recommendations: Sequence[Recommendation]) -> str:
    """Every line must be in one currency, or the total is meaningless.

    Raised rather than converted: ADR-008 keeps money as `Decimal` beside its
    currency and defines no conversion anywhere, so inventing a rate here would
    be inventing a price. The seed catalog is entirely INR, which makes this a
    guard against a future catalog rather than a live condition.
    """
    currencies = {
        recommendation.candidates[0].variant.currency for recommendation in recommendations
    }
    if len(currencies) > 1:
        raise ValueError(f"cannot total a combination across currencies: {sorted(currencies)}")
    return currencies.pop()
