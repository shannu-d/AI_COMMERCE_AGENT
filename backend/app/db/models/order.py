"""``orders``, ``order_items`` and ``idempotency_keys`` — ADR-006, ADR-011, ADR-013.

**`orders.approval_id` is `NOT NULL`, and that single constraint is the
architecture expressed as schema: the database itself refuses to store an
unapproved order.** Not a service check, not a policy rule that could be skipped
on a code path nobody reviewed — a column definition. It makes test fixtures
construct a real approval before they can create an order, which is friction, and
it is exactly the friction the constraint exists to create.

**Order lines are an immutable financial record.** `order_items` snapshots the
SKU, the product name, the variant name and the price at order time, and rows are
never updated afterwards. That denormalization is deliberate and is the *opposite*
of the rule for `cart_items`: a cart must track live catalog state, an order must
show what was bought at the price it was bought for, even after the catalog
changes or the product is deactivated.

**The key→order link lives only on `orders.idempotency_key_id`** (ADR-013), so
the two tables do not form a foreign-key cycle. A replay finds its order by
querying orders on that column rather than by following a pointer the key would
otherwise have to hold before the order existed.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, CurrencyCode, Money, TimestampMixin, uuid_pk
from app.db.models._enums import in_list
from app.domain.commerce import (
    IDEMPOTENCY_SCOPES,
    IDEMPOTENCY_STATUSES,
    ORDER_STATUSES,
    IdempotencyStatus,
    OrderStatus,
)

if TYPE_CHECKING:
    from app.db.models.approval import Approval
    from app.db.models.cart import Cart
    from app.db.models.merchant import Merchant
    from app.db.models.session import Session
    from app.db.models.variant import ProductVariant


class IdempotencyKey(Base):
    """A client-presented key that makes order creation replay-safe (ADR-013).

    `RESERVED` is written **before** the work begins, which is what makes this a
    mutex rather than a receipt. A second request presenting the same key finds
    the reservation and returns the recorded response instead of creating a
    second order.
    """

    __tablename__ = "idempotency_keys"
    __table_args__ = (
        UniqueConstraint("key"),
        CheckConstraint(in_list("scope", IDEMPOTENCY_SCOPES), name="scope_is_known"),
        CheckConstraint(in_list("status", IDEMPOTENCY_STATUSES), name="status_is_known"),
        CheckConstraint("approved_total >= 0", name="approved_total_is_not_negative"),
        CheckConstraint("cart_version >= 1", name="cart_version_starts_at_one"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    key: Mapped[str] = mapped_column(String(128), nullable=False)
    scope: Mapped[str] = mapped_column(String(32), nullable=False)
    session_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("sessions.id"), nullable=False
    )
    cart_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("carts.id"), nullable=False
    )
    #: The key is bound to the exact cart version and total it was minted for, so
    #: replaying it against a changed cart is detectable rather than silently
    #: honoured (ADR-013, ADR-014).
    cart_version: Mapped[int] = mapped_column(Integer, nullable=False)
    approved_total: Mapped[Decimal] = mapped_column(Money, nullable=False)
    currency: Mapped[str] = mapped_column(CurrencyCode, nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default=text(f"'{IdempotencyStatus.RESERVED.value}'")
    )
    #: What a replay returns. Stored so the second caller gets the same answer as
    #: the first rather than a freshly-computed one that may have drifted.
    response_snapshot: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    def __repr__(self) -> str:
        return f"<IdempotencyKey {self.key} {self.status}>"


class Order(Base, TimestampMixin):
    """The internal order of P§18 and P§29. Committed before Razorpay is called."""

    __tablename__ = "orders"
    __table_args__ = (
        UniqueConstraint("idempotency_key_id"),
        UniqueConstraint("razorpay_order_id"),
        CheckConstraint(in_list("status", ORDER_STATUSES), name="status_is_known"),
        CheckConstraint("subtotal_amount >= 0", name="subtotal_is_not_negative"),
        CheckConstraint("total_amount >= 0", name="total_is_not_negative"),
        CheckConstraint("total_amount_minor >= 0", name="total_minor_is_not_negative"),
        CheckConstraint("cart_version >= 1", name="cart_version_starts_at_one"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    merchant_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("merchants.id"), nullable=False
    )
    session_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("sessions.id"), nullable=False
    )
    cart_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("carts.id"), nullable=False
    )
    cart_version: Mapped[int] = mapped_column(Integer, nullable=False)
    #: **NOT NULL.** The invariant as schema — see the module docstring.
    approval_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("approvals.id"), nullable=False
    )
    idempotency_key_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("idempotency_keys.id"), nullable=False
    )
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default=text(f"'{OrderStatus.ORDER_CREATED.value}'")
    )
    currency: Mapped[str] = mapped_column(CurrencyCode, nullable=False)
    subtotal_amount: Mapped[Decimal] = mapped_column(Money, nullable=False)
    total_amount: Mapped[Decimal] = mapped_column(Money, nullable=False)
    #: The exact integer sent to Razorpay (ADR-008). Stored rather than
    #: recomputed, so what was charged and what was recorded cannot diverge if
    #: the conversion is ever changed.
    total_amount_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    #: Null until Razorpay accepts the order — the gap ADR-011 makes recoverable
    #: by committing the internal order first.
    razorpay_order_id: Mapped[str | None] = mapped_column(String(64), nullable=True)

    merchant: Mapped[Merchant] = relationship()
    session: Mapped[Session] = relationship()
    cart: Mapped[Cart] = relationship()
    approval: Mapped[Approval] = relationship()
    idempotency_key: Mapped[IdempotencyKey] = relationship()
    items: Mapped[list[OrderItem]] = relationship(back_populates="order")

    def __repr__(self) -> str:
        return f"<Order {self.id} {self.status} {self.total_amount} {self.currency}>"


class OrderItem(Base):
    """One immutable line of a placed order.

    No `updated_at`, because these rows are never updated. The names and the SKU
    are snapshots: renaming a product must not rewrite what someone bought.
    """

    __tablename__ = "order_items"
    __table_args__ = (
        UniqueConstraint("order_id", "variant_id"),
        CheckConstraint("quantity > 0", name="quantity_is_positive"),
        CheckConstraint("unit_price >= 0", name="unit_price_is_not_negative"),
        CheckConstraint("line_total >= 0", name="line_total_is_not_negative"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    order_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("orders.id", ondelete="RESTRICT"), nullable=False
    )
    #: RESTRICT: a variant that appears in a placed order cannot be deleted. The
    #: financial record outlives the catalog row.
    variant_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("product_variants.id", ondelete="RESTRICT"),
        nullable=False,
    )
    sku: Mapped[str] = mapped_column(String(64), nullable=False)
    product_name: Mapped[str] = mapped_column(String(200), nullable=False)
    variant_name: Mapped[str] = mapped_column(String(200), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    unit_price: Mapped[Decimal] = mapped_column(Money, nullable=False)
    line_total: Mapped[Decimal] = mapped_column(Money, nullable=False)
    currency: Mapped[str] = mapped_column(CurrencyCode, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    order: Mapped[Order] = relationship(back_populates="items")
    variant: Mapped[ProductVariant] = relationship()

    def __repr__(self) -> str:
        return f"<OrderItem {self.sku} x{self.quantity} @ {self.unit_price}>"
