"""The Cart Service (M7; A§13, F§12, F§13, A§27, RULE 6, RULE 12).

Two rules govern every method here, and both are about who is allowed to say what
something costs.

**The backend computes every amount, always.** No method takes a price, a
subtotal or a total. `add_item` takes a variant and a quantity; the price is read
from `product_variants` in the same call and the line total is multiplied here.
A§13 and F§12 are explicit — the frontend never sums line items and the model
never supplies a price — and the way to keep that true is to give neither of them
a parameter through which one could arrive.

**The version increments on any change to composition or to the authoritative
total.** F§13's example is a buyer approving version 7 and then adding a product,
which makes it 8 and the approval stale. It never decrements and is never reset,
because an approval binds to a version number and a reused number would make a
stale approval look current (A§27).

That second rule has a consequence worth stating plainly: **a refresh that finds
a changed price is a mutation.** Nothing the buyer did changed, but what they
would be charged did, so the version moves and any approval bound to the old one
is stale. This is the primary failure scenario the specification names (A§28),
and it is handled here by treating price drift as a cart change rather than as an
incident.

`unit_price_snapshot` is display and drift-detection state, never authority
(RULE 6, RULE 12). Every read path in this module re-reads the live price; the
snapshot exists so the difference can be *shown* to the buyer.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Sequence
from decimal import Decimal

from sqlalchemy.orm import Session

from app.db.models import Cart, CartItem
from app.domain.cart import CartItemView, CartView, PriceDrift
from app.domain.commerce import CartStatus
from app.domain.inventory import StockStatus
from app.repositories.cart_repository import CartRepository
from app.services.catalog_service import CatalogService
from app.services.inventory_service import InventoryService

logger = logging.getLogger(__name__)

__all__ = ["MAX_LINE_QUANTITY", "CartError", "CartService"]

#: A§18's bound on a quantity a model may state, applied to every caller rather
#: than only to the tool: a REST client is no more entitled to order 10,000 cases
#: by typo than the agent is.
MAX_LINE_QUANTITY = 99


class CartError(Exception):
    """A cart operation that cannot be performed, with a machine-readable code.

    The codes are `app.agent.errors.ApiErrorCode` values, so the same failure
    reads identically whether it arrived through a tool or through a REST route.
    Carrying the code here rather than mapping it twice is what keeps them equal.
    """

    def __init__(self, code: str, message: str, *, details: dict | None = None) -> None:
        self.code = code
        self.message = message
        self.details = details or {}
        super().__init__(f"{code}: {message}")


class CartService:
    """Everything that changes a cart, and nothing that authorizes one."""

    def __init__(self, session: Session) -> None:
        self._session = session
        self._carts = CartRepository(session)
        self._catalog = CatalogService(session)
        self._inventory = InventoryService(session)

    # -- reads ---------------------------------------------------------------

    def get_active(self, merchant_id: uuid.UUID, session_id: uuid.UUID) -> CartView | None:
        """The session's live cart, priced from the catalog as it is now.

        Returns `None` rather than creating one: `GET /api/cart` on a session
        that has not started a cart should say so, not quietly mint state.
        """
        cart = self._carts.get_active_for_session(merchant_id, session_id)
        return None if cart is None else self._view(merchant_id, cart)

    def get(self, merchant_id: uuid.UUID, cart_id: uuid.UUID) -> CartView | None:
        cart = self._carts.get(merchant_id, cart_id)
        return None if cart is None else self._view(merchant_id, cart)

    def get_or_create_active(
        self, merchant_id: uuid.UUID, session_id: uuid.UUID, *, currency: str = "INR"
    ) -> CartView:
        cart = self._carts.get_active_for_session(merchant_id, session_id)
        if cart is None:
            cart = self._carts.create(merchant_id, session_id, currency)
            logger.info("cart created", extra={"cart_id": str(cart.id)})
        return self._view(merchant_id, cart)

    # -- mutation ------------------------------------------------------------

    def add_item(
        self,
        merchant_id: uuid.UUID,
        session_id: uuid.UUID,
        variant_id: uuid.UUID,
        quantity: int = 1,
    ) -> CartView:
        """Add a variant, or increase the quantity of the line that has it.

        Takes no price. The authoritative one is read below, from the row the
        `variant_id` resolves to — and a `variant_id` that resolves to nothing is
        an error, never a line with a guessed price (A§30, ADR-009).
        """
        self._check_quantity(quantity)
        variant = self._require_variant(merchant_id, variant_id)
        cart = self._require_active_cart(merchant_id, session_id, variant.currency)

        existing = self._carts.get_item_for_variant(cart.id, variant_id)
        wanted = quantity + (existing.quantity if existing else 0)
        self._check_quantity(wanted)
        self._require_stock(merchant_id, variant_id, wanted, variant.sku)

        if existing is not None:
            existing.quantity = wanted
            existing.unit_price_snapshot = variant.price
            existing.line_total = variant.price * wanted
        else:
            self._carts.add_item(
                cart,
                CartItem(
                    variant_id=variant_id,
                    quantity=quantity,
                    unit_price_snapshot=variant.price,
                    line_total=variant.price * quantity,
                    currency=variant.currency,
                ),
            )

        return self._recompute(merchant_id, cart, changed=True)

    def set_quantity(
        self,
        merchant_id: uuid.UUID,
        session_id: uuid.UUID,
        item_id: uuid.UUID,
        quantity: int,
    ) -> CartView:
        """Set a line's quantity. Zero is a removal, stated as one."""
        if quantity == 0:
            return self.remove_item(merchant_id, session_id, item_id)
        self._check_quantity(quantity)

        cart = self._require_existing_cart(merchant_id, session_id)
        item = self._require_item(cart, item_id)
        variant = self._require_variant(merchant_id, item.variant_id)
        self._require_stock(merchant_id, item.variant_id, quantity, variant.sku)

        item.quantity = quantity
        item.unit_price_snapshot = variant.price
        item.line_total = variant.price * quantity
        return self._recompute(merchant_id, cart, changed=True)

    def remove_item(
        self, merchant_id: uuid.UUID, session_id: uuid.UUID, item_id: uuid.UUID
    ) -> CartView:
        cart = self._require_existing_cart(merchant_id, session_id)
        self._carts.remove_item(self._require_item(cart, item_id))
        return self._recompute(merchant_id, cart, changed=True)

    def replace_items(
        self,
        merchant_id: uuid.UUID,
        session_id: uuid.UUID,
        lines: Sequence[tuple[uuid.UUID, int]],
    ) -> CartView:
        """Set the cart to exactly these `(variant_id, quantity)` pairs.

        What `propose_cart` calls (ADR-009). A proposal replaces rather than
        appends, because the model is describing the cart it means the buyer to
        see; appending would make a second proposal double the first.

        Every variant is resolved and every stock level checked **before**
        anything is written, so a proposal naming one bad variant leaves the
        existing cart untouched instead of half-replaced.
        """
        resolved = []
        for variant_id, quantity in lines:
            self._check_quantity(quantity)
            variant = self._require_variant(merchant_id, variant_id)
            self._require_stock(merchant_id, variant_id, quantity, variant.sku)
            resolved.append((variant, quantity))

        currency = resolved[0][0].currency if resolved else "INR"
        cart = self._require_active_cart(merchant_id, session_id, currency)

        for item in self._carts.items(cart.id):
            self._carts.remove_item(item)
        for variant, quantity in resolved:
            self._carts.add_item(
                cart,
                CartItem(
                    variant_id=variant.id,
                    quantity=quantity,
                    unit_price_snapshot=variant.price,
                    line_total=variant.price * quantity,
                    currency=variant.currency,
                ),
            )
        return self._recompute(merchant_id, cart, changed=True)

    def refresh(self, merchant_id: uuid.UUID, cart_id: uuid.UUID) -> CartView:
        """Re-price every line from the catalog, and version the cart if it moved.

        A price change is a cart change. Nothing the buyer did was different, but
        what they would be charged is, so the version increments and any approval
        bound to the old version is stale (A§27, A§28, ADR-014).
        """
        cart = self._carts.get(merchant_id, cart_id)
        if cart is None:
            raise CartError("VALIDATION_ERROR", "no such cart")

        drifted = False
        for item in self._carts.items(cart.id):
            variant = self._catalog.get_variant(merchant_id, item.variant_id)
            if variant is None:
                continue
            if variant.price != item.unit_price_snapshot:
                drifted = True
                item.unit_price_snapshot = variant.price
                item.line_total = variant.price * item.quantity

        return self._recompute(merchant_id, cart, changed=drifted)

    def mark_ordered(self, merchant_id: uuid.UUID, cart_id: uuid.UUID) -> None:
        """Close the cart once an order exists (M10).

        The version does not move: the cart's composition did not change, and an
        approval bound to this version must stay matched to the order it
        authorized.
        """
        cart = self._carts.get(merchant_id, cart_id)
        if cart is not None:
            cart.status = CartStatus.ORDERED.value

    # -- internals -----------------------------------------------------------

    def _recompute(self, merchant_id: uuid.UUID, cart: Cart, *, changed: bool) -> CartView:
        """Recompute the authoritative totals and bump the version if needed.

        The only place `subtotal_amount`, `total_amount` and `version` are ever
        assigned. `changed` is passed rather than inferred: a caller that
        rewrote a line to the same values has not changed the cart, and bumping
        the version for it would invalidate an approval for nothing.
        """
        items = self._carts.items(cart.id)
        subtotal = sum((item.line_total for item in items), Decimal("0.00"))
        cart.subtotal_amount = subtotal
        # Subtotal and total are equal until shipping or tax exists. Kept as two
        # columns because F§12 names both and the day they diverge should be a
        # change to this line, not a schema migration.
        cart.total_amount = subtotal
        if changed:
            cart.version += 1
        self._session.flush()
        return self._view(merchant_id, cart)

    def _view(self, merchant_id: uuid.UUID, cart: Cart) -> CartView:
        """A cart priced from the catalog as it is right now.

        The live price is read per line, so a `CartView` is always current even
        if nothing has called `refresh`. The snapshot is compared against it and
        any difference is reported as drift rather than silently corrected —
        correcting it here would change what the buyer is charged without their
        seeing it happen.
        """
        items: list[CartItemView] = []
        drift: list[PriceDrift] = []
        for item in self._carts.items(cart.id):
            variant = self._catalog.get_variant(merchant_id, item.variant_id)
            if variant is None:
                continue
            stock = self._inventory.check_availability(merchant_id, item.variant_id, item.quantity)
            if variant.price != item.unit_price_snapshot:
                drift.append(
                    PriceDrift(
                        variant_id=variant.id,
                        sku=variant.sku,
                        product_name=variant.product_name,
                        previous_unit_price=item.unit_price_snapshot,
                        current_unit_price=variant.price,
                    )
                )
            items.append(
                CartItemView(
                    id=item.id,
                    variant_id=variant.id,
                    product_id=variant.product_id,
                    sku=variant.sku,
                    product_name=variant.product_name,
                    variant_name=variant.name,
                    quantity=item.quantity,
                    unit_price=item.unit_price_snapshot,
                    line_total=item.line_total,
                    currency=item.currency,
                    stock_status=stock.status.value,
                    available=stock.available,
                )
            )

        return CartView(
            id=cart.id,
            session_id=cart.session_id,
            status=CartStatus(cart.status),
            version=cart.version,
            currency=cart.currency,
            subtotal=cart.subtotal_amount,
            total=cart.total_amount,
            items=tuple(items),
            drift=tuple(drift),
        )

    def _require_active_cart(
        self, merchant_id: uuid.UUID, session_id: uuid.UUID, currency: str
    ) -> Cart:
        cart = self._carts.get_active_for_session(merchant_id, session_id)
        return cart if cart is not None else self._carts.create(merchant_id, session_id, currency)

    def _require_existing_cart(self, merchant_id: uuid.UUID, session_id: uuid.UUID) -> Cart:
        cart = self._carts.get_active_for_session(merchant_id, session_id)
        if cart is None:
            raise CartError("VALIDATION_ERROR", "this session has no active cart")
        return cart

    def _require_item(self, cart: Cart, item_id: uuid.UUID) -> CartItem:
        item = self._carts.get_item(cart.id, item_id)
        if item is None:
            raise CartError("VALIDATION_ERROR", "no such item in this cart")
        return item

    def _require_variant(self, merchant_id: uuid.UUID, variant_id: uuid.UUID):
        """A model- or client-supplied id is a lookup key, never a fact (A§30)."""
        variant = self._catalog.get_variant(merchant_id, variant_id)
        if variant is None:
            raise CartError(
                "VARIANT_NOT_FOUND",
                "that product is not in this catalog",
                details={"variant_id": str(variant_id)},
            )
        return variant

    def _require_stock(
        self, merchant_id: uuid.UUID, variant_id: uuid.UUID, quantity: int, sku: str
    ) -> None:
        """RULE 5: nothing unpurchasable goes in a cart.

        Checked at every mutation *and* re-checked by the Policy Engine inside
        the order transaction (ADR-011). This one is so the buyer finds out now;
        that one is so it is still true when the money moves.
        """
        check = self._inventory.check_availability(merchant_id, variant_id, quantity)
        if not check.available:
            raise CartError(
                "OUT_OF_STOCK",
                f"{sku} is not available in the quantity requested",
                details={
                    "variant_id": str(variant_id),
                    "sku": sku,
                    # Coarse only (ADR-009, closing E5).
                    "stock_status": check.status.value
                    if check.status is not StockStatus.NO_RECORD
                    else StockStatus.OUT_OF_STOCK.value,
                },
            )

    @staticmethod
    def _check_quantity(quantity: int) -> None:
        if quantity < 1 or quantity > MAX_LINE_QUANTITY:
            raise CartError(
                "VALIDATION_ERROR",
                f"quantity must be between 1 and {MAX_LINE_QUANTITY}",
            )
