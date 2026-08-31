"""Why a product placed where it did (R§17 RULE 10; ADR-004, open question A7).

The ranking engine writes the reason, not the model. ADR-004 is blunt about
why: a model-authored reason would be an ungrounded claim about a computation
the model did not perform, and A§54's requirement that Claude "should not
arbitrarily change Product C → rank 1" is unenforceable if the justification is
also the model's to write.

So the explanation is derived from the same arithmetic that produced the
ordering — the component scores, the weights applied, the winning component and
the margin over the next candidate — and reduced to one of three fixed labels.
The model may paraphrase the label in prose. The structured field is what the
frontend renders.
"""

from __future__ import annotations

from decimal import Decimal

from app.domain import Explanation, RecommendationLabel, ScoreBreakdown

__all__ = ["explain"]


def explain(breakdown: ScoreBreakdown, *, rank: int, next_score: Decimal | None) -> Explanation:
    """Derive the label, winning component and margin for one placed candidate.

    The rule, in full, because "deterministic" means someone can check it:

    * rank 1 is `BEST_OVERALL` — it won on the weighted total, which is the
      question that was asked;
    * otherwise, a candidate whose largest contribution came from the price term
      is `BEST_PRICE`;
    * otherwise `CLOSEST_MATCH`, since what carried it was preference,
      relevance or compatibility — all statements about fit.

    `margin` is the lead over the next candidate, or `None` for the last, which
    has nothing to lead. It is the number that answers "was this close?" without
    anyone re-deriving the scores.
    """
    winner = breakdown.winning_component
    if rank == 1:
        label = RecommendationLabel.BEST_OVERALL
    elif winner.name == "price":
        label = RecommendationLabel.BEST_PRICE
    else:
        label = RecommendationLabel.CLOSEST_MATCH

    margin = None if next_score is None else breakdown.final_score - next_score
    return Explanation(label=label, winning_component=winner.name, margin=margin)
