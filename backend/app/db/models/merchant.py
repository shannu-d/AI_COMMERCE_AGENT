"""``merchants`` — architecture.md D§4.

The merchant that owns a catalog. CircuitCraft is the MVP example and is
deliberately not hard-coded into the schema (D§4): the seed loader supplies it
as data, and merchant scoping is configuration (ADR-002).
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, CheckConstraint, String, Text, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import CURRENCY_REGEX, Base, CurrencyCode, TimestampMixin, uuid_pk

if TYPE_CHECKING:
    from app.db.models.category import Category
    from app.db.models.product import Product
    from app.db.models.variant import ProductVariant


class Merchant(Base, TimestampMixin):
    __tablename__ = "merchants"
    __table_args__ = (
        # Not in D§4. Added so the seed loader can address a merchant by its
        # natural key and so two CircuitCraft rows cannot coexist.
        UniqueConstraint("name"),
        CheckConstraint(f"currency ~ '{CURRENCY_REGEX}'", name="currency_is_iso4217"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    currency: Mapped[str] = mapped_column(
        CurrencyCode, nullable=False, server_default=text("'INR'")
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))

    categories: Mapped[list[Category]] = relationship(
        back_populates="merchant", cascade="all, delete-orphan"
    )
    products: Mapped[list[Product]] = relationship(
        back_populates="merchant", cascade="all, delete-orphan"
    )
    variants: Mapped[list[ProductVariant]] = relationship(
        back_populates="merchant", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<Merchant {self.name!r} currency={self.currency}>"
