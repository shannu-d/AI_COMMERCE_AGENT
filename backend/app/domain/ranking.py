"""Ranking domain types — what the ranker is asked, and what it answers.

These are the inputs and outputs of the deterministic recommendation pipeline
(ADR-004, ADR-005). They are frozen, they carry `Decimal` money and `Decimal`
scores, and they contain no ORM row, no session and no model output.

The one type worth reading carefully is `ProductRequirement`. It draws the line
the whole ranking layer is built on:

* `required_attributes` **eliminate** — a product that does not satisfy them is
  removed and never scored;
* `preferences` are **scored** — they change the order, never the membership.

ADR-005 puts that distinction in the intent schema rather than in heuristics
over the buyer's phrasing, precisely so it is visible and testable here. The
model populates both fields; the *consequence* of the classification is fixed
in code.

`compatibility_target` is a `ResolvedTarget`, never a string the model wrote.
Requiring the resolved type makes it impossible to rank against a device phrase
that was never canonicalized — an unresolvable phrase is a question for the
buyer (ADR-003), and it cannot reach this layer at all.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field
from decimal import Decimal
from enum import StrEnum
from typing import Any

from app.domain.catalog import ProductSummary, VariantView
from app.domain.compatibility import ResolvedTarget
from app.domain.inventory import StockStatus

__all__ = [
    "LABEL_TEXT",
    "RELAXABLE_CONSTRAINTS",
    "CombinationItem",
    "CombinationOutcome",
    "ConstraintFailure",
    "CrossSellCandidate",
    "Explanation",
    "FilterResult",
    "HardConstraint",
    "MultiProductRecommendation",
    "ProductCombination",
    "ProductRequirement",
    "RankedCandidate",
    "Recommendation",
    "RecommendationLabel",
    "RecommendationOutcome",
    "RejectedCandidate",
    "ScoreBreakdown",
    "WeightedComponent",
]


class HardConstraint(StrEnum):
    """The seven eliminating conditions, in the order D§29 applies them.

    Every one of these removes a candidate; none of them lowers a score
    (ADR-005). D§15 states the failure that rule prevents: an incompatible
    product with a very cheap price must not be able to win on aggregate.
    """

    EXISTENCE = "EXISTENCE"
    MERCHANT = "MERCHANT"
    CATEGORY = "CATEGORY"
    BUDGET = "BUDGET"
    COMPATIBILITY = "COMPATIBILITY"
    REQUIRED_SPECIFICATION = "REQUIRED_SPECIFICATION"
    INVENTORY = "INVENTORY"


#: The constraints that may be relaxed to offer a real catalog *alternative*
#: when nothing matched (ADR-005, R§14).
#:
#: Compatibility is never relaxed — a case for a different phone is not an
#: alternative, it is a wrong answer. Inventory is never relaxed either, because
#: RULE 5 forbids presenting an out-of-stock product as purchasable, and an
#: "alternative" the buyer cannot buy is not an alternative. Category is not
#: relaxed because a charger is not a lesser case. Merchant and existence are
#: not business preferences at all.
RELAXABLE_CONSTRAINTS: frozenset[HardConstraint] = frozenset(
    {HardConstraint.BUDGET, HardConstraint.REQUIRED_SPECIFICATION}
)


@dataclass(frozen=True, slots=True)
class ProductRequirement:
    """One product type the buyer asked for.

    A multi-product request ("a case and a charger") is a list of these, and
    Top-K is applied per requirement rather than across the request (ADR-004,
    closing open question A6) — three cases and three chargers, not three items.
    """

    #: Stable identifier for this requirement within a request, used to key
    #: Top-K and the combination search. Typically the category slug, but named
    #: separately because one request may ask for two things in one category.
    label: str
    category_slug: str | None = None
    #: Free text used only as a *relevance signal* (R§9). It is never a filter:
    #: eliminating on text would silently hide products whose description
    #: happens to use different words.
    query_text: str | None = None
    #: Eliminating. See the class docstring.
    required_attributes: Mapping[str, Any] = field(default_factory=dict)
    #: Scored, never eliminating.
    preferences: Mapping[str, Any] = field(default_factory=dict)
    #: Per-item ceiling. Hard (R§8, D§30): a product above it is removed, not
    #: ranked low.
    max_price: Decimal | None = None
    quantity: int = 1
    #: Already canonicalized (ADR-003). `None` means the buyer stated no
    #: compatibility requirement, not "compatibility does not matter".
    compatibility_target: ResolvedTarget | None = None

    def __post_init__(self) -> None:
        if self.quantity < 1:
            raise ValueError("quantity must be at least 1")
        if self.max_price is not None and self.max_price <= 0:
            raise ValueError("max_price must be greater than zero when stated")

    @property
    def stated_attributes(self) -> dict[str, Any]:
        """Everything the buyer said about attributes, requirements winning.

        This is what the relevance scorer's `attribute_match` term measures
        against (ADR-004). Preferences deliberately appear in both this and
        `PreferenceScore`: R§9 lists "requested attributes match" as a relevance
        signal in its own right, so the overlap is the specification's, not an
        accident. A requirement and a preference on the same key is not
        contradictory — the requirement wins, because it already eliminated
        everything that failed it.
        """
        return {**self.preferences, **self.required_attributes}


@dataclass(frozen=True, slots=True)
class ConstraintFailure:
    """One hard constraint a candidate failed, and why, in plain words."""

    constraint: HardConstraint
    detail: str


@dataclass(frozen=True, slots=True)
class RejectedCandidate:
    """A candidate that was eliminated, with **every** constraint it failed.

    Every constraint, not merely the first: deciding whether a product is an
    honest alternative requires knowing it failed only a relaxable constraint
    (ADR-005). Recording just the first would make a product rejected for both
    budget and compatibility look like a budget-only near miss.
    """

    variant: VariantView
    failures: tuple[ConstraintFailure, ...]

    @property
    def constraints(self) -> frozenset[HardConstraint]:
        return frozenset(failure.constraint for failure in self.failures)

    @property
    def primary(self) -> ConstraintFailure:
        """The first failure, in D§29 evaluation order."""
        return self.failures[0]

    @property
    def is_relaxable(self) -> bool:
        """Whether every constraint it failed is one that may be relaxed."""
        return bool(self.constraints) and self.constraints <= RELAXABLE_CONSTRAINTS


@dataclass(frozen=True, slots=True)
class FilterResult:
    """The outcome of hard filtering: who survived, and why the rest did not."""

    survivors: tuple[VariantView, ...]
    rejected: tuple[RejectedCandidate, ...]

    def rejected_by(self, constraint: HardConstraint) -> tuple[RejectedCandidate, ...]:
        return tuple(r for r in self.rejected if constraint in r.constraints)

    @property
    def relaxable_rejections(self) -> tuple[RejectedCandidate, ...]:
        """Candidates that failed only relaxable constraints — alternative material."""
        return tuple(r for r in self.rejected if r.is_relaxable)


@dataclass(frozen=True, slots=True)
class WeightedComponent:
    """One feature score and the weight applied to it.

    Kept as a record rather than folded into a total, because RULE 10 requires
    the ranking to be explainable and an explanation that cannot show its
    arithmetic is an assertion.
    """

    name: str
    score: Decimal
    weight: Decimal

    @property
    def contribution(self) -> Decimal:
        return self.score * self.weight


@dataclass(frozen=True, slots=True)
class ScoreBreakdown:
    """`FinalScore` and every term that produced it."""

    profile_name: str
    components: tuple[WeightedComponent, ...]
    final_score: Decimal

    def component(self, name: str) -> WeightedComponent | None:
        return next((c for c in self.components if c.name == name), None)

    @property
    def winning_component(self) -> WeightedComponent:
        """The term contributing most to the total.

        Ties break on component order, which the aggregator fixes, so this is
        deterministic (RULE 8).
        """
        return max(self.components, key=lambda c: c.contribution)


class RecommendationLabel(StrEnum):
    """The deterministic reason label (ADR-004, closing open question A7).

    Derived from the same arithmetic that produced the ordering, by the ranking
    engine, never written by the model. The model may paraphrase it in prose;
    this field is what the frontend renders, because a model-authored reason
    would be an ungrounded claim about a computation it did not perform.
    """

    BEST_OVERALL = "BEST_OVERALL"
    BEST_PRICE = "BEST_PRICE"
    CLOSEST_MATCH = "CLOSEST_MATCH"


LABEL_TEXT: dict[RecommendationLabel, str] = {
    RecommendationLabel.BEST_OVERALL: "Best overall",
    RecommendationLabel.BEST_PRICE: "Best price",
    RecommendationLabel.CLOSEST_MATCH: "Closest match to your requirements",
}


@dataclass(frozen=True, slots=True)
class Explanation:
    """Why a candidate placed where it did."""

    label: RecommendationLabel
    winning_component: str
    #: `FinalScore` lead over the next candidate; `None` for the last one, which
    #: has nothing to lead.
    margin: Decimal | None

    @property
    def text(self) -> str:
        return LABEL_TEXT[self.label]


@dataclass(frozen=True, slots=True)
class RankedCandidate:
    """One scored, placed candidate."""

    rank: int
    variant: VariantView
    score: ScoreBreakdown
    explanation: Explanation
    #: Coarse status only. Exact quantities stay inside the services and the
    #: Policy Engine (ADR-009, ADR-010, closing open question E5).
    stock_status: StockStatus

    @property
    def final_score(self) -> Decimal:
        return self.score.final_score


class RecommendationOutcome(StrEnum):
    """What the pipeline actually found (ADR-005, R§14).

    Three outcomes rather than "results or none", because they call for
    different next actions and because an alternative presented as a match is
    the failure R§14 forbids.
    """

    EXACT_MATCH = "EXACT_MATCH"
    NO_MATCH_WITH_ALTERNATIVES = "NO_MATCH_WITH_ALTERNATIVES"
    NO_MATCH = "NO_MATCH"


@dataclass(frozen=True, slots=True)
class Recommendation:
    """The answer for one `ProductRequirement`."""

    requirement: ProductRequirement
    outcome: RecommendationOutcome
    profile_name: str
    candidates: tuple[RankedCandidate, ...] = ()
    #: Real catalog products that failed only a relaxable constraint. They are
    #: **never** presented as matches, and `relaxed_constraints` names what each
    #: one did not meet so the agent can say so out loud.
    alternatives: tuple[RankedCandidate, ...] = ()
    relaxed_constraints: tuple[HardConstraint, ...] = ()
    rejected: tuple[RejectedCandidate, ...] = ()

    @property
    def has_match(self) -> bool:
        return self.outcome is RecommendationOutcome.EXACT_MATCH


class CombinationOutcome(StrEnum):
    """Whether a multi-product request fits its overall budget (R§13)."""

    WITHIN_BUDGET = "WITHIN_BUDGET"
    NO_COMBINATION_WITHIN_BUDGET = "NO_COMBINATION_WITHIN_BUDGET"
    #: At least one requested product type had no candidate at all. Reported
    #: rather than dropped: ADR-004 forbids silently answering a two-product
    #: request with one product.
    INCOMPLETE = "INCOMPLETE"


@dataclass(frozen=True, slots=True)
class CombinationItem:
    """One line of a proposed combination. Not a cart — nothing here is reserved."""

    label: str
    candidate: RankedCandidate
    quantity: int

    @property
    def line_total(self) -> Decimal:
        return self.candidate.variant.price * self.quantity


@dataclass(frozen=True, slots=True)
class ProductCombination:
    """The chosen set of products for a multi-product request."""

    outcome: CombinationOutcome
    items: tuple[CombinationItem, ...] = ()
    total: Decimal = Decimal("0.00")
    currency: str | None = None
    total_budget: Decimal | None = None
    #: Requirement labels with no candidate, when the outcome is INCOMPLETE.
    missing_labels: tuple[str, ...] = ()
    #: Summed `FinalScore` of the chosen items — the quantity the search
    #: maximizes, kept so the choice is inspectable.
    combined_score: Decimal = Decimal("0")

    @property
    def fits_budget(self) -> bool:
        return self.outcome is CombinationOutcome.WITHIN_BUDGET


@dataclass(frozen=True, slots=True)
class MultiProductRecommendation:
    """Per-requirement recommendations plus the combination that fits the budget."""

    recommendations: tuple[Recommendation, ...]
    combination: ProductCombination

    def for_label(self, label: str) -> Recommendation | None:
        return next((r for r in self.recommendations if r.requirement.label == label), None)


@dataclass(frozen=True, slots=True)
class CrossSellCandidate:
    """A cross-sell offer that has already been validated (R§15).

    Every check R§15 lists has passed before one of these exists: the product
    exists, it is compatible with the buyer's device, it is in stock, and it has
    a real price. It is a candidate of the *relationship*, so it can never be a
    random product that merely increases revenue.
    """

    product: ProductSummary
    variant: VariantView
    relationship_type: str
    priority: int
    stock_status: StockStatus

    @property
    def variant_id(self) -> uuid.UUID:
        return self.variant.id
