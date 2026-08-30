"""``inventory`` — architecture.md D§11, D§12.

Stock belongs to the sellable variant, not to the product: one product's black
variant can be in stock while its blue variant is not, and storing stock on the
product would lose that (D§12).

``available_quantity = quantity - reserved_quantity`` (D§11). For the MVP
``reserved_quantity`` stays at 0 — no reservation mechanism is implemented, and
the residual race between the policy check and order creation is closed instead
by a row lock inside one transaction (ADR-005, ADR-011).

The specification gives this table an ``updated_at`` and no ``created_at``
(D§11), and the schema follows it rather than adding a column for symmetry.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, ForeignKey, Integer, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, UpdatedAtMixin, uuid_pk

if TYPE_CHECKING:
    from app.db.models.variant import ProductVariant


class Inventory(Base, UpdatedAtMixin):
    __tablename__ = "inventory"
    __table_args__ = (
        # D§11, D§23: exactly one inventory record per variant.
        UniqueConstraint("variant_id"),
        CheckConstraint("quantity >= 0", name="quantity_is_not_negative"),
        CheckConstraint("reserved_quantity >= 0", name="reserved_quantity_is_not_negative"),
        # Available quantity is a derived value and must never be negative.
        CheckConstraint("reserved_quantity <= quantity", name="reserved_quantity_within_quantity"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    variant_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("product_variants.id", ondelete="CASCADE"),
        nullable=False,
    )
    quantity: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    reserved_quantity: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )

    variant: Mapped[ProductVariant] = relationship(back_populates="inventory")

    @property
    def available_quantity(self) -> int:
        """D§11. The value every availability check uses."""
        return self.quantity - self.reserved_quantity

    def __repr__(self) -> str:
        return f"<Inventory variant={self.variant_id} available={self.available_quantity}>"
