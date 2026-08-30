"""``product_variants`` — architecture.md D§8, D§9, D§10.

The sellable unit. SKU, price, currency and (through ``inventory``) stock all
belong here, because a product's variants can differ in every one of them
(D§9, D§12).

``price`` is ``NUMERIC(12,2)`` and reaches Python as a ``Decimal``. Integer
minor units exist only at the Razorpay boundary, converted in exactly one module
(ADR-008). No float ever touches a price.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import (
    CURRENCY_REGEX,
    SKU_REGEX,
    Base,
    CurrencyCode,
    Money,
    TimestampMixin,
    uuid_pk,
)

if TYPE_CHECKING:
    from app.db.models.inventory import Inventory
    from app.db.models.merchant import Merchant
    from app.db.models.product import Product


class ProductVariant(Base, TimestampMixin):
    __tablename__ = "product_variants"
    __table_args__ = (
        # D§10, D§23, D§24: one SKU per merchant, so two merchants may reuse a
        # SKU string without colliding.
        UniqueConstraint("merchant_id", "sku"),
        # A variant's product must belong to the same merchant.
        ForeignKeyConstraint(
            ["merchant_id", "product_id"],
            ["products.merchant_id", "products.id"],
            name="fk_product_variants_product_within_merchant",
            ondelete="CASCADE",
        ),
        CheckConstraint(f"sku ~ '{SKU_REGEX}'", name="sku_is_uppercase_token"),
        CheckConstraint("price >= 0", name="price_is_not_negative"),
        CheckConstraint(f"currency ~ '{CURRENCY_REGEX}'", name="currency_is_iso4217"),
        CheckConstraint("jsonb_typeof(attributes) = 'object'", name="attributes_is_object"),
        # Loading a product's variants is the single most common catalog join.
        Index("ix_product_variants_product_id", "product_id"),
        Index("ix_product_variants_is_active", "is_active"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    merchant_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("merchants.id", ondelete="CASCADE"),
        nullable=False,
    )
    product_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("products.id", ondelete="CASCADE"),
        nullable=False,
    )
    sku: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    price: Mapped[Decimal] = mapped_column(Money, nullable=False)
    currency: Mapped[str] = mapped_column(CurrencyCode, nullable=False)
    attributes: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))

    merchant: Mapped[Merchant] = relationship(back_populates="variants")
    product: Mapped[Product] = relationship(back_populates="variants", foreign_keys=[product_id])
    inventory: Mapped[Inventory | None] = relationship(
        back_populates="variant", cascade="all, delete-orphan", uselist=False
    )

    def __repr__(self) -> str:
        return f"<ProductVariant {self.sku!r} {self.currency} {self.price}>"
