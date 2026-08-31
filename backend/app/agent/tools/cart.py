"""`propose_cart` (T6, M7; ADR-009, A§13).

The first MEDIUM-tier tool. It writes application state and moves no money, and
the distance between those two facts is the whole design:

**It computes nothing.** `ProposeCartArgs` has no price field, no subtotal and no
total — only `(variant_id, quantity)` pairs. The authoritative price for each
variant is read from `product_variants` by the Cart Service, and the total is
multiplied there. A model-supplied amount would be an unverified claim about
money, and it would be the claim the buyer is then asked to approve.

**It proposes; it does not authorize.** A cart is a draft. Nothing in this module
writes an approval, and nothing downstream treats a cart as one — an order needs
a row in `approvals`, and `orders.approval_id NOT NULL` means the database
refuses otherwise.

**It replaces rather than appends.** The model is describing the cart it means
the buyer to see, so a second proposal is a correction of the first and not an
addition to it. Appending would make "actually, just the case" produce a cart
holding the case twice.

The session is `TurnMemory`'s, set by the runtime from the loaded conversation.
No tool schema has a `session_id` field, so there is no argument through which a
model could name somebody else's cart.
"""

from __future__ import annotations

import uuid
from typing import Any

from app.agent.context import AgentContext, TurnMemory
from app.agent.errors import ToolError, ToolErrorCode
from app.agent.tools._serialize import money
from app.llm.tool_schemas import ProposeCartArgs
from app.services.cart_service import CartError

__all__ = ["propose_cart", "serialize_cart"]

#: How a `CartError` code reads to the model. The service speaks F§25's public
#: vocabulary already, so this maps back into the runtime's finer one rather than
#: inventing a third.
_CODES: dict[str, ToolErrorCode] = {
    "VARIANT_NOT_FOUND": ToolErrorCode.VARIANT_NOT_FOUND,
    "OUT_OF_STOCK": ToolErrorCode.OUT_OF_STOCK,
    "VALIDATION_ERROR": ToolErrorCode.INVALID_ARGUMENTS,
}


def serialize_cart(cart: Any) -> dict[str, Any]:
    """A `CartView` as the model and the frontend both see it (F§12, F§13).

    Money is a fixed-scale string throughout, and `cart_version` is present
    because it is what an approval binds to — a client that renders a total
    without it cannot tell a stale confirmation screen from a current one.
    """
    payload: dict[str, Any] = {
        "cart_id": str(cart.id),
        "cart_version": cart.version,
        "currency": cart.currency,
        "subtotal": money(cart.subtotal),
        "total": money(cart.total),
        "items": [
            {
                "item_id": str(item.id),
                "variant_id": str(item.variant_id),
                "product_id": str(item.product_id),
                "sku": item.sku,
                "name": item.product_name,
                "variant_name": item.variant_name,
                "quantity": item.quantity,
                "unit_price": money(item.unit_price),
                "line_total": money(item.line_total),
                "currency": item.currency,
                "stock_status": item.stock_status,
                "available": item.available,
            }
            for item in cart.items
        ],
    }
    if cart.drift:
        # ADR-014: drift is reported in the buyer's terms, both directions. A
        # cheaper cart is still not the cart they agreed to.
        payload["price_changes"] = [
            {
                "sku": change.sku,
                "name": change.product_name,
                "previous_unit_price": money(change.previous_unit_price),
                "current_unit_price": money(change.current_unit_price),
                "increased": change.increased,
            }
            for change in cart.drift
        ]
    return payload


def propose_cart(
    context: AgentContext, memory: TurnMemory, args: ProposeCartArgs
) -> dict[str, Any]:
    """T6. Set the buyer's cart to exactly the lines proposed.

    Every variant is resolved and every stock level checked before anything is
    written, so a proposal naming one bad variant leaves the existing cart
    untouched rather than half-replaced.
    """
    session_id = memory.require_session()

    lines: list[tuple[uuid.UUID, int]] = []
    for item in args.items:
        try:
            variant_id = uuid.UUID(item.variant_id)
        except (ValueError, AttributeError) as exc:
            raise ToolError(
                ToolErrorCode.VARIANT_NOT_FOUND,
                f"no variant matching {item.variant_id!r} exists in this catalog",
            ) from exc
        lines.append((variant_id, item.quantity))

    try:
        cart = context.carts.replace_items(context.merchant_id, session_id, lines)
    except CartError as error:
        raise ToolError(
            _CODES.get(error.code, ToolErrorCode.INTERNAL_ERROR),
            error.message,
            details=error.details,
        ) from error

    payload = serialize_cart(cart)
    # Said explicitly, because it is the thing the model most needs to not get
    # wrong: a proposed cart is not a purchase and not an approval.
    payload["status"] = "PROPOSED"
    return payload
