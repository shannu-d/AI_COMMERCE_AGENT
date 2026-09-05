"""`search_catalog` and `get_product` (A§18, ADR-009, T1 and T2).

`search_catalog` is the tool that makes the whole architecture work, and what it
does *not* do is the point: it does not hand the model a list to reason over. It
runs the buyer's requirements through the deterministic pipeline — catalog query,
hard constraints, ranking — and returns what the ranker placed. R§11 and A§52 are
explicit that the runtime must not ask Claude to inspect every product manually.

So the model's influence stops at the arguments. It names a category, a budget,
some words and some attributes; the ordering, the reasons and the scores come
back from `app.ranking`, which cannot import `app.llm` and has never seen the
conversation.
"""

from __future__ import annotations

import uuid
from typing import Any

from app.agent.context import AgentContext, TurnMemory
from app.agent.errors import ToolError, ToolErrorCode
from app.agent.tools._serialize import serialize_product, serialize_ranked_for_model
from app.domain.ranking import ProductRequirement, RecommendationOutcome
from app.llm.tool_schemas import GetProductArgs, SearchCatalogArgs

__all__ = ["get_product", "search_catalog"]


def _parse_uuid(value: str, code: ToolErrorCode, field: str) -> uuid.UUID:
    """A model-supplied identifier is a lookup key, never a fact (A§30).

    A malformed one fails as *not found* rather than as a validation error,
    because from the buyer's point of view the difference between "that is not a
    real id" and "no such product" is nothing at all — and reporting the parse
    failure separately would tell the model something about the id format it has
    no use for.
    """
    try:
        return uuid.UUID(value)
    except (ValueError, AttributeError) as exc:
        raise ToolError(code, f"no {field} matching {value!r} exists in this catalog") from exc


def search_catalog(
    context: AgentContext, memory: TurnMemory, args: SearchCatalogArgs
) -> dict[str, Any]:
    """T1. Ranked, grounded results for the buyer's stated requirements.

    The category is validated against the merchant's real slugs before anything
    else. It is already a JSON-schema enum built from those slugs (ADR-009,
    closing B2), so a model that respects the schema cannot get here with a bad
    one — this is the second check, for a model that does not.
    """
    if args.category is not None and not context.catalog.category_exists(
        context.merchant_id, args.category
    ):
        raise ToolError(
            ToolErrorCode.CATEGORY_NOT_FOUND,
            f"{args.category!r} is not a category this merchant sells",
        )

    requirement = ProductRequirement(
        label=args.category or "search",
        category_slug=args.category,
        query_text=args.search_query,
        # Attributes the buyer *stated* are eliminating (ADR-005). They arrive
        # here as required, not preferred, because A§18 calls them requirements
        # and the ranker's preference term is fed from the extracted intent
        # rather than from a tool argument.
        required_attributes=dict(args.attributes),
        max_price=args.max_price,
    )

    result = context.recommendations.recommend(context.merchant_id, requirement)
    memory.recommendations[requirement.label] = result

    payload: dict[str, Any] = {
        "outcome": result.outcome.value,
        "results": [serialize_ranked_for_model(candidate) for candidate in result.candidates],
    }

    # R§14: an alternative is never presented as a match. It travels in its own
    # field, with the constraint it failed named, so the agent can say what it
    # is rather than quietly offering it as an answer.
    if result.outcome is not RecommendationOutcome.EXACT_MATCH:
        payload["alternatives"] = [serialize_ranked_for_model(c) for c in result.alternatives]
        payload["relaxed_constraints"] = [c.value for c in result.relaxed_constraints]

    return payload


def get_product(context: AgentContext, memory: TurnMemory, args: GetProductArgs) -> dict[str, Any]:
    """T2. One product and its variants, by id or SKU.

    Exactly one key is supplied — the argument schema enforces that — and a miss
    is an error rather than an empty result (A§30, ADR-009). An empty result
    would be a shape the model could describe as "no longer available"; an error
    with a code is one it must report.
    """
    if args.sku is not None:
        variant = context.catalog.get_variant_by_sku(context.merchant_id, args.sku)
        if variant is None:
            raise ToolError(
                ToolErrorCode.VARIANT_NOT_FOUND,
                f"no product with SKU {args.sku!r} exists in this catalog",
            )
        product_id = variant.product_id
    else:
        assert args.product_id is not None  # guaranteed by the argument schema
        product_id = _parse_uuid(args.product_id, ToolErrorCode.PRODUCT_NOT_FOUND, "product")

    detail = context.catalog.get_product(context.merchant_id, product_id)
    if detail is None:
        raise ToolError(
            ToolErrorCode.PRODUCT_NOT_FOUND,
            f"no product with id {product_id} exists in this catalog",
        )

    payload = serialize_product(detail)
    # Stock rides alongside each variant, coarsely (ADR-009, closing E5). A
    # product page that showed a price without saying whether it can be bought
    # is how "it's available" gets said without anyone checking.
    statuses = context.inventory.get_stock_map(
        context.merchant_id, [variant.id for variant in detail.variants]
    )
    for entry in payload["variants"]:
        stock = statuses.get(uuid.UUID(entry["variant_id"]))
        if stock is not None:
            entry["stock_status"] = stock.status.value
    return payload
