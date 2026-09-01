"""Cart request and response models (M7; F§12, F§13, ADR-008).

**No request model here has a money field, and that is the contract.** F§12 says
the frontend never sums line items and A§13 says nobody but the backend states a
price; the way to hold both is to give a client nowhere to put one. Every model
is `extra="forbid"`, so a request carrying `unit_price` or `total` is a 422
rather than a field quietly discarded — a discarded field looks honoured.

Money leaves as a fixed-scale **string** (ADR-008). Typing these as `Decimal`
would still serialize as a JSON number in most encoders, and the whole point is
that a client's parser never sees one.

`cart_version` is on every response because it is what an approval binds to
(F§13, A§27). A confirmation screen rendered without it cannot tell a current
total from one the buyer already agreed to and that has since moved.
"""

from __future__ import annotations

import uuid
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.domain.cart import CartView

__all__ = [
    "AddItemRequest",
    "ApprovalResponse",
    "ApproveCartRequest",
    "CartItemResponse",
    "CartResponse",
    "PriceChange",
    "UpdateItemRequest",
]

#: A§18's bound, restated at the edge so a bad request fails before a service
#: has to raise. The service checks it too, because a tool call does not come
#: through here.
MAX_QUANTITY = 99


class AddItemRequest(BaseModel):
    """`(variant_id, quantity)` and nothing else."""

    model_config = ConfigDict(extra="forbid")

    session_id: uuid.UUID
    variant_id: uuid.UUID = Field(
        description="A lookup key. One that does not resolve is a 404, never a guessed product."
    )
    quantity: int = Field(default=1, ge=1, le=MAX_QUANTITY)


class UpdateItemRequest(BaseModel):
    """A new quantity for an existing line. Zero removes it."""

    model_config = ConfigDict(extra="forbid")

    session_id: uuid.UUID
    quantity: int = Field(ge=0, le=MAX_QUANTITY)


class CartItemResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    item_id: uuid.UUID
    variant_id: uuid.UUID
    product_id: uuid.UUID
    sku: str
    name: str
    variant_name: str
    quantity: int
    #: Fixed-scale strings. See the module docstring.
    unit_price: str
    line_total: str
    currency: str
    #: Coarse only — exact quantities never appear in a buyer-facing payload
    #: (ADR-009, closing E5).
    stock_status: str
    available: bool


class PriceChange(BaseModel):
    """A line whose live price differs from what the buyer last saw (ADR-014).

    Reported in both directions. A cheaper cart is still not the cart the buyer
    agreed to, and an approval bound to the old total is stale either way.
    """

    model_config = ConfigDict(extra="forbid")

    sku: str
    name: str
    previous_unit_price: str
    current_unit_price: str
    increased: bool


class CartResponse(BaseModel):
    """The authoritative cart. Every amount computed by the backend."""

    model_config = ConfigDict(extra="forbid")

    cart_id: uuid.UUID
    cart_version: int = Field(description="What an approval binds to (F§13, A§27).")
    status: str
    currency: str
    subtotal: str
    total: str
    items: list[CartItemResponse] = Field(default_factory=list)
    price_changes: list[PriceChange] = Field(default_factory=list)

    @classmethod
    def of(cls, cart: CartView) -> CartResponse:
        """Build from the service's view.

        Serialization goes through `app.agent.tools.cart.serialize_cart`, the
        same function the agent's `propose_cart` returns and the chat response
        embeds, so a cart looks identical however the buyer reached it. Two
        renderings of one cart would eventually disagree about a total.
        """
        from app.agent.tools.cart import serialize_cart

        payload: dict[str, Any] = serialize_cart(cart)
        payload["status"] = cart.status.value
        payload.setdefault("price_changes", [])
        return cls.model_validate(payload)


class ApproveCartRequest(BaseModel):
    """A buyer's authorization of one exact cart state (ADR-007).

    `cart_version` is **required**, and it is what the buyer's screen was
    showing rather than what the cart is now. Submitting it is the whole
    mechanism by which a stale view becomes detectable instead of being silently
    applied to whatever the cart has since become (A§26, A§27).

    `expected_total` is optional and checked when supplied — the same idea said
    twice, because a client that renders a total should be able to say which one
    it rendered. It is a **string**, so a client cannot send a float that a
    parser has already rounded.
    """

    model_config = ConfigDict(extra="forbid")

    session_id: uuid.UUID
    cart_version: int = Field(
        ge=1, description="The version the buyer was looking at, not the current one."
    )
    expected_total: str | None = Field(
        default=None,
        description='The total the buyer saw, as a fixed-scale string, e.g. "1499.00".',
    )


class ApprovalResponse(BaseModel):
    """What an approval looks like once recorded.

    The cart travels with it because the confirmation screen and the record must
    agree: an approval is a claim about a specific cart state, and returning one
    without that state would make it unverifiable by the client that just made
    it.
    """

    model_config = ConfigDict(extra="forbid")

    approval_id: uuid.UUID
    status: str
    cart_version: int
    approved_total: str
    currency: str
    approved_at: str | None
    expires_at: str
    #: Minted with this approval and bound to its exact state (ADR-013). The
    #: client presents it on `POST /api/orders`; presenting it twice yields one
    #: order and the same answer. `None` only for an approval recorded before
    #: M10 existed.
    idempotency_key: str | None = None
    cart: CartResponse
