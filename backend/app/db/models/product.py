"""``products`` — architecture.md D§6, D§7.

The conceptual product: "what is this", as opposed to the variant's "which exact
sellable version" (D§8). SKU, price and stock deliberately live on the variant,
not here (D§10, D§12; ADR-002).

``attributes`` is JSONB because product characteristics vary by industry and
hundreds of nullable columns would be a bad schema (D§7, D§26). What must never
go in there is anything commerce depends on — merchant, category, identity, SKU,
price, inventory, compatibility all stay first-class columns (D§7).

``attributes`` describes the product; it never encodes compatibility. "This
charger is 65W" is an attribute; "this charger works with a MacBook Air M3" is a
row in ``compatibility_rules`` (D§28).
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import CANONICAL_TOKEN_REGEX, Base, TimestampMixin, uuid_pk

if TYPE_CHECKING:
    from app.db.models.category import Category
    from app.db.models.compatibility import CompatibilityRule
    from app.db.models.merchant import Merchant
    from app.db.models.relationship import ProductRelationship
    from app.db.models.variant import ProductVariant


class Product(Base, TimestampMixin):
    __tablename__ = "products"
    __table_args__ = (
        # D§23.
        UniqueConstraint("merchant_id", "slug"),
        # Target for the composite foreign key on product_variants.
        UniqueConstraint("merchant_id", "id"),
        # A product's category must belong to the same merchant. The plain
        # category_id foreign key below satisfies D§22; this one additionally
        # makes cross-merchant assignment impossible rather than merely
        # discouraged.
        ForeignKeyConstraint(
            ["merchant_id", "category_id"],
            ["categories.merchant_id", "categories.id"],
            name="fk_products_category_within_merchant",
            ondelete="RESTRICT",
        ),
        CheckConstraint(f"slug ~ '{CANONICAL_TOKEN_REGEX}'", name="slug_is_canonical_token"),
        CheckConstraint("jsonb_typeof(attributes) = 'object'", name="attributes_is_object"),
        # D§24, verbatim. The first is partly covered by the unique constraint
        # above; it is created because the specification names it.
        Index("ix_products_merchant_id", "merchant_id"),
        Index("ix_products_category_id", "category_id"),
        Index("ix_products_merchant_id_category_id", "merchant_id", "category_id"),
        Index("ix_products_is_active", "is_active"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    merchant_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("merchants.id", ondelete="CASCADE"),
        nullable=False,
    )
    # NOT NULL: category is a hard constraint in the recommendation pipeline
    # (R§2 step 4), and a product with no category could never satisfy it.
    category_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("categories.id", ondelete="RESTRICT"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(160), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    brand: Mapped[str | None] = mapped_column(String(128), nullable=True)
    attributes: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    tags: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, server_default=text("'{}'::text[]")
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))

    merchant: Mapped[Merchant] = relationship(back_populates="products")
    category: Mapped[Category] = relationship(back_populates="products", foreign_keys=[category_id])
    variants: Mapped[list[ProductVariant]] = relationship(
        back_populates="product",
        cascade="all, delete-orphan",
        foreign_keys="ProductVariant.product_id",
    )
    compatibility_rules: Mapped[list[CompatibilityRule]] = relationship(
        back_populates="product", cascade="all, delete-orphan"
    )
    related_products: Mapped[list[ProductRelationship]] = relationship(
        back_populates="source_product",
        cascade="all, delete-orphan",
        foreign_keys="ProductRelationship.source_product_id",
    )

    def __repr__(self) -> str:
        return f"<Product {self.slug!r}>"
