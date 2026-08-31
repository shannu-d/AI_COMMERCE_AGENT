"""Cart domain values (ADR-006, F§12, F§13, A§13).

Frozen views, like the catalog's. A service returns one of these rather than an
ORM row, so nothing downstream can mutate a cart by assigning to an attribute
and nothing carries a live session into a response.

**Every money value here was computed by the backend.** F§12 is explicit that
the frontend never sums line items, and A§13 that the model never supplies a
price. These types have no constructor path that accepts a client-supplied
total: `CartView.of` derives the totals from the lines it is given, and the lines
carry prices read from `product_variants` in the same call.

`PriceDrift` is the reason `cart_items.unit_price_snapshot` exists at all. The
authoritative price is always the live one; the snapshot is what the buyer was
last shown, and the difference between them is a fact the buyer has to be told
about in their own terms — "was ₹1,499, now ₹1,799" (ADR-014).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from decimal import Decimal

from app.domain.commerce import CartStatus

__all__ = ["CartItemView", "CartView", "PriceDrift"]


@dataclass(frozen=True, slots=True)
class PriceDrift:
    """One line whose live price differs from what the buyer last saw."""

    variant_id: uuid.UUID
    sku: str
    product_name: str
    previous_unit_price: Decimal
    current_unit_price: Decimal

    @property
    def increased(self) -> bool:
        return self.current_unit_price > self.previous_unit_price

    @property
    def difference(self) -> Decimal:
        """Signed, so a drop reads as negative rather than as an increase."""
        return self.current_unit_price - self.previous_unit_price


@dataclass(frozen=True, slots=True)
class CartItemView:
    """One line, with the identity a buyer needs to recognise it."""

    id: uuid.UUID
    variant_id: uuid.UUID
    product_id: uuid.UUID
    sku: str
    product_name: str
    variant_name: str
    quantity: int
    unit_price: Decimal
    line_total: Decimal
    currency: str
    #: Coarse only, as everywhere buyer-facing (ADR-009, closing E5).
    stock_status: str
    #: Whether this line can still be bought at this quantity, checked live.
    available: bool = True


@dataclass(frozen=True, slots=True)
class CartView:
    """A cart and its backend-computed totals."""

    id: uuid.UUID
    session_id: uuid.UUID
    status: CartStatus
    #: F§13's `cart_version`. What an approval binds to (A§27).
    version: int
    currency: str
    subtotal: Decimal
    total: Decimal
    items: tuple[CartItemView, ...] = ()
    #: Populated when a refresh found a live price differing from the snapshot.
    #: Empty is the normal case and means the buyer is looking at current prices.
    drift: tuple[PriceDrift, ...] = ()

    @property
    def is_empty(self) -> bool:
        return not self.items

    @property
    def item_count(self) -> int:
        """Total units, not lines. Two of one case is two items."""
        return sum(item.quantity for item in self.items)

    @property
    def has_unavailable_items(self) -> bool:
        """RULE 5: a cart containing something nobody can buy is not orderable."""
        return any(not item.available for item in self.items)

    @property
    def has_drifted(self) -> bool:
        return bool(self.drift)
