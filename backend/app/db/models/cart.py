"""``carts`` and ``cart_items`` — ADR-006, F§12, F§13.

Two rules here are the ones a later change is most likely to break.

**The totals are backend-computed, always** (A§13, F§12). No API accepts them,
no tool proposes them, and the frontend never sums line items. The columns exist
so the computed value has somewhere to live between turns, not so anyone can
supply one.

**`unit_price_snapshot` is display and drift-detection state, never authority**
(RULE 6, RULE 12). The authoritative price is re-read from `product_variants`
inside the order transaction, every time. The snapshot exists precisely so drift
can be *detected* and explained — "was ₹1,499, now ₹1,799" — which is impossible
if nothing remembers what the buyer was last shown.

That makes `cart_items` the opposite of `order_items` on purpose: cart lines
track live catalog state, order lines are an immutable financial record.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, CurrencyCode, Money, TimestampMixin, uuid_pk
from app.db.models._enums import in_list
from app.domain.commerce import CART_STATUSES, CartStatus

if TYPE_CHECKING:
    from app.db.models.merchant import Merchant
    from app.db.models.session import Session
    from app.db.models.variant import ProductVariant


class Cart(Base, TimestampMixin):
    """One buyer's working set of items."""

    __tablename__ = "carts"
    __table_args__ = (
        CheckConstraint(in_list("status", CART_STATUSES), name="status_is_known"),
        CheckConstraint("version >= 1", name="version_starts_at_one"),
        CheckConstraint("subtotal_amount >= 0", name="subtotal_is_not_negative"),
        CheckConstraint("total_amount >= 0", name="total_is_not_negative"),
        # One active cart per session. Partial, because a session accumulates
        # ORDERED and ABANDONED carts over its life and only the live one is
        # exclusive.
        Index(
            "uq_carts_session_id_active",
            "session_id",
            unique=True,
            postgresql_where=text("status = 'ACTIVE'"),
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    merchant_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("merchants.id"), nullable=False
    )
    session_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("sessions.id"), nullable=False
    )
    status: Mapped[str] = mapped_column(
        String(24), nullable=False, server_default=text(f"'{CartStatus.ACTIVE.value}'")
    )
    #: F§13's `cart_version`. Increments on **any** change to composition or to
    #: the authoritative total — item added, removed, quantity changed, or a
    #: refresh that finds a different price. Never decrements, never resets.
    #: This is the value an approval binds to (A§27).
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    currency: Mapped[str] = mapped_column(CurrencyCode, nullable=False)
    subtotal_amount: Mapped[Decimal] = mapped_column(
        Money, nullable=False, server_default=text("0")
    )
    total_amount: Mapped[Decimal] = mapped_column(Money, nullable=False, server_default=text("0"))

    merchant: Mapped[Merchant] = relationship()
    session: Mapped[Session] = relationship()
    items: Mapped[list[CartItem]] = relationship(
        back_populates="cart", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<Cart {self.id} v{self.version} {self.status}>"


class CartItem(Base, TimestampMixin):
    """One line. `(variant_id, quantity)` and the computed money."""

    __tablename__ = "cart_items"
    __table_args__ = (
        UniqueConstraint("cart_id", "variant_id"),
        CheckConstraint("quantity > 0", name="quantity_is_positive"),
        CheckConstraint("unit_price_snapshot >= 0", name="unit_price_is_not_negative"),
        CheckConstraint("line_total >= 0", name="line_total_is_not_negative"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    cart_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("carts.id", ondelete="CASCADE"), nullable=False
    )
    #: RESTRICT, not CASCADE: deleting a variant that is in someone's cart should
    #: fail loudly rather than silently emptying it.
    variant_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("product_variants.id", ondelete="RESTRICT"),
        nullable=False,
    )
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    #: The price when this line was last refreshed. **Not** authority — see the
    #: module docstring.
    unit_price_snapshot: Mapped[Decimal] = mapped_column(Money, nullable=False)
    line_total: Mapped[Decimal] = mapped_column(Money, nullable=False)
    currency: Mapped[str] = mapped_column(CurrencyCode, nullable=False)

    cart: Mapped[Cart] = relationship(back_populates="items")
    variant: Mapped[ProductVariant] = relationship()

    def __repr__(self) -> str:
        return f"<CartItem {self.variant_id} x{self.quantity}>"
