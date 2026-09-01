"""Order request and response models (M10; ADR-011, ADR-013, ADR-008).

**The request carries no money.** A session, a cart, a claimed `cart_version` and
an idempotency key the backend minted — and `extra="forbid"`, so a client sending
`amount` or `total` gets a 422 rather than a field quietly discarded. F§17's
forged `amount = ₹1` is not defeated by validation here; it simply has nowhere to
be submitted.

`cart_version` is accepted and is *a claim to be checked*, not an instruction: if
it does not match the cart's current version the Policy Engine refuses.

The response carries the amount twice, as a fixed-scale string and as the integer
minor units, because they are different facts. The string is what a buyer is
shown; the integer is exactly what a payment provider will be sent, and storing
and returning it means what was recorded and what will be charged came from one
conversion (ADR-008).
"""

from __future__ import annotations

import uuid

from pydantic import BaseModel, ConfigDict, Field

__all__ = ["CreateOrderRequest", "OrderResponse"]


class CreateOrderRequest(BaseModel):
    """Everything a client may say about an order it wants created."""

    model_config = ConfigDict(extra="forbid")

    session_id: uuid.UUID
    cart_id: uuid.UUID
    cart_version: int = Field(
        ge=1, description="A claim to be checked against the cart, not an instruction."
    )
    idempotency_key: str = Field(
        min_length=1,
        max_length=128,
        description=(
            "The key the backend minted when the cart was approved, returned with the "
            "approval. Presenting it twice yields one order and the same answer."
        ),
    )


class OrderResponse(BaseModel):
    """An order, or the one a replay found.

    `replayed` is present so a client can tell "I created this" from "this
    already existed" without inspecting the status code, which matters for a
    retry after a network timeout — the case idempotency exists for.
    """

    model_config = ConfigDict(extra="forbid")

    order_id: uuid.UUID
    status: str
    total_amount: str
    total_amount_minor: int
    currency: str
    #: Null until Razorpay accepts the order (M11). An order in `ORDER_CREATED`
    #: with this null is the state ADR-011 designs for, not a broken one.
    razorpay_order_id: str | None = None
    replayed: bool = False

    @classmethod
    def of(cls, result, *, replayed: bool = False) -> OrderResponse:
        return cls(
            order_id=result.order_id,
            status=result.status.value,
            total_amount=str(result.total_amount),
            total_amount_minor=result.total_amount_minor,
            currency=result.currency,
            replayed=replayed,
        )

    @classmethod
    def from_row(cls, order) -> OrderResponse:
        return cls(
            order_id=order.id,
            status=order.status,
            total_amount=str(order.total_amount),
            total_amount_minor=order.total_amount_minor,
            currency=order.currency,
            razorpay_order_id=order.razorpay_order_id,
        )
