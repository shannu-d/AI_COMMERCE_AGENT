"""``product_relationships`` — architecture.md D§16, D§17.

Cross-sell, bundle and related-product links. A table rather than a
``cross_sell_product_id`` column on ``products``, because one product has many
related products (D§17): a phone case cross-sells a screen protector, a cleaning
kit and a camera protector.

A relationship is a *candidate*, never a recommendation. R§15 requires cross-sell
suggestions to be grounded in compatibility, catalog data, bundle rules and user
intent — so the recommendation service still filters these candidates by
compatibility and stock before any of them is offered, and the system never
suggests a product merely because it raises order value.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Final

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, uuid_pk

if TYPE_CHECKING:
    from app.db.models.product import Product

#: D§16.
PRODUCT_RELATIONSHIP_TYPES: Final[tuple[str, ...]] = ("cross_sell", "bundle", "related")


class ProductRelationship(Base):
    __tablename__ = "product_relationships"
    __table_args__ = (
        UniqueConstraint(
            "source_product_id",
            "target_product_id",
            "relationship_type",
            name="uq_product_relationships_pair_type",
        ),
        CheckConstraint(
            "source_product_id <> target_product_id", name="source_differs_from_target"
        ),
        CheckConstraint(
            "relationship_type IN ("
            + ", ".join(f"'{value}'" for value in PRODUCT_RELATIONSHIP_TYPES)
            + ")",
            name="relationship_type_is_known",
        ),
        CheckConstraint("priority >= 0", name="priority_is_not_negative"),
        # D§24, verbatim: relationships are always looked up from the source.
        Index("ix_product_relationships_source_product_id", "source_product_id"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    source_product_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("products.id", ondelete="CASCADE"),
        nullable=False,
    )
    target_product_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("products.id", ondelete="CASCADE"),
        nullable=False,
    )
    relationship_type: Mapped[str] = mapped_column(String(32), nullable=False)
    #: Lower sorts first: 1 is the strongest suggestion.
    priority: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))

    # D§16 lists created_at only.
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    source_product: Mapped[Product] = relationship(
        back_populates="related_products", foreign_keys=[source_product_id]
    )
    target_product: Mapped[Product] = relationship(foreign_keys=[target_product_id])

    def __repr__(self) -> str:
        return f"<ProductRelationship {self.relationship_type} priority={self.priority}>"
