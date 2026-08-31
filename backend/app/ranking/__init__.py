"""The ranking engine (M3) — the whole of `architecture.md` Part R, in code.

    hard filter (ADR-005)  ->  four feature scores (ADR-004)
                           ->  weighted sum  ->  deterministic sort  ->  Top-K

Two properties hold across every module here, and both are load-bearing:

**It is pure.** No session, no query, no HTTP call, no clock, no randomness.
Inputs are domain values and configuration; outputs are domain values. That is
what lets the specification's own worked example (R§10) be a unit test, and it
is why `RecommendationService` — not this package — is where the database
appears.

**The model is absent.** R§11 forbids the LLM from computing a ranking score,
and ADR-001 forbids this side of the boundary from importing the LLM layer at
all. The model contributes the *intent* that becomes a `ProductRequirement`, and
nothing else: not a score, not an order, not a reason string, not a weight.
"""

from app.ranking.combinations import SEARCH_DEPTH, combine
from app.ranking.explain import explain
from app.ranking.filters import apply_hard_constraints
from app.ranking.ranker import DEFAULT_TOP_K, aggregate, rank, recommend, score_variant
from app.ranking.scorers import (
    compatibility_score,
    preference_score,
    price_denominator,
    price_score,
    relevance_score,
)
from app.ranking.weights import (
    DEFAULT_PROFILE_NAME,
    PROFILE_NAMES,
    PROFILES,
    UnknownWeightProfileError,
    WeightProfile,
    get_profile,
)

__all__ = [
    "DEFAULT_PROFILE_NAME",
    "DEFAULT_TOP_K",
    "PROFILES",
    "PROFILE_NAMES",
    "SEARCH_DEPTH",
    "UnknownWeightProfileError",
    "WeightProfile",
    "aggregate",
    "apply_hard_constraints",
    "combine",
    "compatibility_score",
    "explain",
    "get_profile",
    "preference_score",
    "price_denominator",
    "price_score",
    "rank",
    "recommend",
    "relevance_score",
    "score_variant",
]
