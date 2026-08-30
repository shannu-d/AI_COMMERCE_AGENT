"""``categories`` — architecture.md D§5.

Hierarchical via a nullable self-reference. The seed builds the tree D§5
illustrates: Electronics → Mobile Accessories → Phone Cases, and Electronics →
Laptop Accessories → Laptop Sleeves.

``slug`` matters beyond tidiness. It is the value the agent's ``search_catalog``
tool is constrained to choose from, enumerated into the tool schema so the model
cannot invent a category that does not exist (ADR-009, closing open question
B2). The CHECK constraint keeps every slug in canonical token form.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import CANONICAL_TOKEN_REGEX, Base, TimestampMixin, uuid_pk

if TYPE_CHECKING:
    from app.db.models.merchant import Merchant
    from app.db.models.product import Product


class Category(Base, TimestampMixin):
    __tablename__ = "categories"
    __table_args__ = (
        # D§23: prevents duplicate category slugs for one merchant.
        UniqueConstraint("merchant_id", "slug"),
        # Target for the composite foreign key on products, which is what keeps
        # a product and its category inside the same merchant.
        UniqueConstraint("merchant_id", "id"),
        CheckConstraint(f"slug ~ '{CANONICAL_TOKEN_REGEX}'", name="slug_is_canonical_token"),
        CheckConstraint("parent_id IS NULL OR parent_id <> id", name="parent_is_not_self"),
        Index("ix_categories_parent_id", "parent_id"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    merchant_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("merchants.id", ondelete="CASCADE"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(128), nullable=False)
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("categories.id", ondelete="SET NULL"),
        nullable=True,
    )

    merchant: Mapped[Merchant] = relationship(back_populates="categories")
    parent: Mapped[Category | None] = relationship(
        back_populates="children", remote_side="Category.id"
    )
    children: Mapped[list[Category]] = relationship(back_populates="parent")
    # products carries two foreign key paths to categories: the plain
    # category_id key D§22 specifies, and the composite merchant-scoping key
    # (ADR-002). The plain one is the relationship.
    products: Mapped[list[Product]] = relationship(
        back_populates="category", foreign_keys="Product.category_id"
    )

    def __repr__(self) -> str:
        return f"<Category {self.slug!r}>"
