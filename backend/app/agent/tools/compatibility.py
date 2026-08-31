"""`get_compatible_products` (T3, ADR-003, ADR-009).

This is where the subtlest rule in the system is enforced. The model is
forbidden from deciding compatibility, and the model is nonetheless what
produces the device phrase that gets matched. ADR-003 closes the gap with a
pipeline, and this tool is its entry point:

    buyer text -> [LLM] a phrase -> normalize_token -> resolve against
    compatibility_targets -> canonical id -> query compatibility_rules

The tool takes the buyer's own words and hands them to
`CompatibilityService.resolve_target`. It never constructs a canonical
identifier itself, never falls back to substring matching, and never widens the
search to obtain results.

**Unresolvable or ambiguous means ask the buyer.** Both come back as errors with
distinct codes, because they need different questions: "which device do you
have?" against "did you mean this one or that one?". Neither is a no-match, and
conflating the two would tell a buyer their phone is unsupported when the truth
is that the phrase was unclear.
"""

from __future__ import annotations

from typing import Any

from app.agent.context import AgentContext, TurnMemory
from app.agent.errors import ToolError, ToolErrorCode
from app.agent.tools._serialize import serialize_ranked
from app.domain.compatibility import ResolutionFailure, ResolvedTarget
from app.domain.ranking import ProductRequirement, RecommendationOutcome
from app.llm.tool_schemas import GetCompatibleProductsArgs

__all__ = ["get_compatible_products", "resolve_device"]


def resolve_device(context: AgentContext, memory: TurnMemory, phrase: str) -> ResolvedTarget:
    """The device phrase, resolved to a canonical target, or an error.

    Cached for the turn: a buyer who says "iPhone 16" once should not be asked
    about it twice because two tools happened to need it. The cache is
    `TurnMemory`, so it dies with the turn — a device resolved three turns ago is
    re-resolved, because the vocabulary may have changed and the cost is one
    indexed lookup.
    """
    if phrase in memory.resolved_devices:
        return memory.resolved_devices[phrase]

    resolution = context.compatibility.resolve_target(phrase)
    if not resolution.resolved:
        if resolution.reason is ResolutionFailure.AMBIGUOUS_TARGET:
            raise ToolError(
                ToolErrorCode.DEVICE_AMBIGUOUS,
                f"{phrase!r} matches more than one device. Ask the buyer which one they mean.",
                details={
                    "device": phrase,
                    # Real choices, so the agent can offer them rather than ask
                    # an open question the buyer has already tried to answer.
                    "candidates": [
                        {
                            "identifier": candidate.canonical_identifier,
                            "display_name": candidate.display_name,
                        }
                        for candidate in resolution.candidates
                    ],
                },
            )
        raise ToolError(
            ToolErrorCode.DEVICE_NOT_RESOLVED,
            (
                f"{phrase!r} is not a device this merchant has compatibility data for. "
                "Ask the buyer for the exact model rather than guessing."
            ),
            details={"device": phrase, "reason": resolution.reason.value},
        )

    memory.resolved_devices[phrase] = resolution
    return resolution


def get_compatible_products(
    context: AgentContext, memory: TurnMemory, args: GetCompatibleProductsArgs
) -> dict[str, Any]:
    """T3. Products that fit a named device, ranked.

    The compatibility constraint is never relaxed to produce results (ADR-005):
    a case for a different phone is a wrong answer, not a lesser one. If nothing
    compatible exists, the outcome says so and any alternatives travel in their
    own field, having failed only a *relaxable* constraint such as the budget.
    """
    target = resolve_device(context, memory, args.device)

    if args.category is not None and not context.catalog.category_exists(
        context.merchant_id, args.category
    ):
        raise ToolError(
            ToolErrorCode.CATEGORY_NOT_FOUND,
            f"{args.category!r} is not a category this merchant sells",
        )

    requirement = ProductRequirement(
        label=args.category or "compatible",
        category_slug=args.category,
        max_price=args.max_price,
        # A `ResolvedTarget`, never the phrase. The type is what closes the
        # ADR-003 pipeline: a string the model wrote cannot reach the ranker.
        compatibility_target=target,
    )

    result = context.recommendations.recommend(context.merchant_id, requirement)
    memory.recommendations[requirement.label] = result

    payload: dict[str, Any] = {
        "device": {
            "identifier": target.canonical_identifier,
            "display_name": target.display_name,
        },
        "outcome": result.outcome.value,
        "results": [serialize_ranked(candidate) for candidate in result.candidates],
    }
    if result.outcome is not RecommendationOutcome.EXACT_MATCH:
        payload["alternatives"] = [serialize_ranked(c) for c in result.alternatives]
        payload["relaxed_constraints"] = [c.value for c in result.relaxed_constraints]
    return payload
