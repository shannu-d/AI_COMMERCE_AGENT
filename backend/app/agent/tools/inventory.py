"""`check_inventory` and `get_upsell_candidates` (T4 and T5, ADR-009).

`check_inventory` is the tool the system prompt points at when it forbids
claiming something is in stock. It is the only place an exact quantity is
computed, and even here the *quantity* stays inside: the payload says whether
the requested amount can be bought and how coarse the position is, never how
many are left (ADR-009, closing E5). A merchant's stock level is their business,
and a buyer who is told "only 2 left" has been told something the architecture
never promised to keep true by the time they check out.

`get_upsell_candidates` is R§15's cross-sell pipeline, which starts from a
`product_relationships` row rather than from a search. That ordering is the whole
safeguard: an accessory is offered because the merchant recorded that it relates
to this product, not because something cheap happened to match. R§15's closing
line — the system must not recommend random products merely because they increase
revenue — is enforced by where the candidates come from, not by the prompt.
"""

from __future__ import annotations

import uuid
from typing import Any

from app.agent.context import AgentContext, TurnMemory
from app.agent.errors import ToolError, ToolErrorCode
from app.agent.tools._serialize import serialize_cross_sell
from app.agent.tools.compatibility import resolve_device
from app.llm.tool_schemas import CheckInventoryArgs, GetUpsellCandidatesArgs

__all__ = ["check_inventory", "get_upsell_candidates"]


def check_inventory(
    context: AgentContext, memory: TurnMemory, args: CheckInventoryArgs
) -> dict[str, Any]:
    """T4. Whether `quantity` of one variant can be bought right now.

    The comparison is `available >= requested` (D§29 step 6), not merely
    non-zero: a buyer asking for three of something with two in stock has not
    been told yes.

    Out of stock is a **successful call with a negative answer**, not an error.
    The agent needs to say "that one is unavailable, here is what is" — which it
    can only do if the call returned facts rather than raising.
    """
    if args.sku is not None:
        variant = context.catalog.get_variant_by_sku(context.merchant_id, args.sku)
        if variant is None:
            raise ToolError(
                ToolErrorCode.VARIANT_NOT_FOUND,
                f"no variant with SKU {args.sku!r} exists in this catalog",
            )
        variant_id = variant.id
    else:
        assert args.variant_id is not None  # guaranteed by the argument schema
        try:
            variant_id = uuid.UUID(args.variant_id)
        except (ValueError, AttributeError) as exc:
            raise ToolError(
                ToolErrorCode.VARIANT_NOT_FOUND,
                f"no variant matching {args.variant_id!r} exists in this catalog",
            ) from exc
        variant = context.catalog.get_variant(context.merchant_id, variant_id)
        if variant is None:
            raise ToolError(
                ToolErrorCode.VARIANT_NOT_FOUND,
                f"no variant with id {variant_id} exists in this catalog",
            )

    check = context.inventory.check_availability(context.merchant_id, variant_id, args.quantity)
    return {
        "variant_id": str(variant.id),
        "sku": variant.sku,
        "requested_quantity": check.requested_quantity,
        "available": check.available,
        # Coarse only. `check.available_quantity` exists and is deliberately not
        # serialized here (ADR-009, closing E5).
        "stock_status": check.status.value,
    }


def get_upsell_candidates(
    context: AgentContext, memory: TurnMemory, args: GetUpsellCandidatesArgs
) -> dict[str, Any]:
    """T5. Accessories the merchant related to a product, filtered and ranked.

    Every check R§15 lists has already passed by the time a candidate exists:
    the product exists, it is compatible with the buyer's device if one was
    named, it is in stock, and it has a real price. An empty list is a normal
    answer — most products have no accessories, and inventing some would be the
    exact failure R§15 forbids.
    """
    try:
        product_id = uuid.UUID(args.product_id)
    except (ValueError, AttributeError) as exc:
        raise ToolError(
            ToolErrorCode.PRODUCT_NOT_FOUND,
            f"no product matching {args.product_id!r} exists in this catalog",
        ) from exc

    if context.catalog.get_product(context.merchant_id, product_id) is None:
        raise ToolError(
            ToolErrorCode.PRODUCT_NOT_FOUND,
            f"no product with id {product_id} exists in this catalog",
        )

    # A device narrows the offers to what actually fits. An unresolvable phrase
    # raises here rather than being dropped: silently offering incompatible
    # accessories is worse than asking which phone the buyer has.
    target = None if args.device is None else resolve_device(context, memory, args.device)

    candidates = context.recommendations.cross_sell_candidates(
        context.merchant_id, product_id, target=target
    )
    return {
        "product_id": str(product_id),
        "candidates": [serialize_cross_sell(candidate) for candidate in candidates],
    }
