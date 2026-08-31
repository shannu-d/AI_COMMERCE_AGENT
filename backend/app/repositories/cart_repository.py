"""Cart persistence, merchant-scoped like every other repository (ADR-002).

Reads and writes rows. It computes no totals and decides no versions — those are
the service's, because they are business rules and this layer is a query.

The one thing it does own is `for_update`, which takes `SELECT ... FOR UPDATE` on
the cart row. ADR-006 and ADR-011 need the Policy Engine's live re-check and the
order insert to happen in one transaction with the relevant rows locked; the lock
belongs where the query is.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.db.models import Cart, CartItem, ProductVariant
from app.domain.commerce import CartStatus

__all__ = ["CartRepository"]


class CartRepository:
    """Reads and writes `carts` and `cart_items`."""

    def __init__(self, session: Session) -> None:
        self._session = session

    # -- reads ---------------------------------------------------------------

    def get(self, merchant_id: uuid.UUID, cart_id: uuid.UUID) -> Cart | None:
        return self._session.execute(
            self._select().where(Cart.id == cart_id, Cart.merchant_id == merchant_id)
        ).scalar_one_or_none()

    def get_active_for_session(self, merchant_id: uuid.UUID, session_id: uuid.UUID) -> Cart | None:
        """The session's live cart, if it has one.

        At most one can exist — a partial unique index enforces that — so this is
        `scalar_one_or_none` rather than a "first" that would hide a duplicate.
        """
        return self._session.execute(
            self._select().where(
                Cart.merchant_id == merchant_id,
                Cart.session_id == session_id,
                Cart.status == CartStatus.ACTIVE.value,
            )
        ).scalar_one_or_none()

    def for_update(self, merchant_id: uuid.UUID, cart_id: uuid.UUID) -> Cart | None:
        """The cart row, locked until the transaction ends (ADR-006, closing C6).

        Without this there is a window between "the total was computed" and "the
        order was created" in which another request can change the cart.
        """
        return self._session.execute(
            select(Cart)
            .where(Cart.id == cart_id, Cart.merchant_id == merchant_id)
            .with_for_update()
        ).scalar_one_or_none()

    def _select(self):
        # The items and their variants are loaded eagerly because every caller
        # needs them: a cart without its lines cannot have a total.
        return select(Cart).options(
            selectinload(Cart.items)
            .selectinload(CartItem.variant)
            .selectinload(ProductVariant.product)
        )

    def get_item(self, cart_id: uuid.UUID, item_id: uuid.UUID) -> CartItem | None:
        return self._session.execute(
            select(CartItem).where(CartItem.id == item_id, CartItem.cart_id == cart_id)
        ).scalar_one_or_none()

    def get_item_for_variant(self, cart_id: uuid.UUID, variant_id: uuid.UUID) -> CartItem | None:
        """The existing line for a variant, if any.

        Adding a variant that is already in the cart increases its quantity
        rather than creating a second line — `UNIQUE(cart_id, variant_id)` would
        refuse the second anyway, and failing there would be a database error
        where the buyer meant something perfectly sensible.
        """
        return self._session.execute(
            select(CartItem).where(CartItem.cart_id == cart_id, CartItem.variant_id == variant_id)
        ).scalar_one_or_none()

    # -- writes --------------------------------------------------------------

    def create(self, merchant_id: uuid.UUID, session_id: uuid.UUID, currency: str) -> Cart:
        cart = Cart(
            merchant_id=merchant_id,
            session_id=session_id,
            status=CartStatus.ACTIVE.value,
            currency=currency,
        )
        self._session.add(cart)
        self._session.flush()
        return cart

    def add_item(self, cart: Cart, item: CartItem) -> CartItem:
        item.cart_id = cart.id
        self._session.add(item)
        self._session.flush()
        return item

    def remove_item(self, item: CartItem) -> None:
        self._session.delete(item)
        self._session.flush()

    def items(self, cart_id: uuid.UUID) -> Sequence[CartItem]:
        return list(
            self._session.execute(
                select(CartItem)
                .where(CartItem.cart_id == cart_id)
                .options(selectinload(CartItem.variant).selectinload(ProductVariant.product))
                .order_by(CartItem.created_at, CartItem.id)
            ).scalars()
        )
