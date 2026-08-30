"""``compatibility_rules`` — architecture.md D§13, D§14, D§15, D§28.

Compatibility is its own concept, not a product attribute (D§28), and it is a
hard filter rather than a scoring dimension: an incompatible product is removed
before ranking, never allowed to outrank a compatible one on price (D§15,
R§17 RULE 4; ADR-005).

Two decisions from ADR-003 are enforced here by the database rather than by
convention.

``target_identifier`` must be a canonical lowercase token. The model never
supplies one directly — it extracts a phrase, which the application normalizes
and resolves against ``compatibility_targets``. The CHECK makes a mixed-case or
space-bearing identifier impossible to insert, so a resolution bug cannot
quietly write an unmatchable row.

``rule_type`` permits only ``compatible``. ``incompatible`` and ``requires`` are
reserved but *not* allowed, because a value the filter does not know how to
interpret is worse than a value that cannot be stored. Widening the enum is a
migration plus a superseding ADR, in the same change that defines the semantics.

``constraints`` holds predicates evaluated against **the product's own
attributes** (ADR-003, closing open question B3). ``{"minimum_wattage": 20,
"fast_charge": true}`` on a charger reads "compatible with this device provided
this product supplies at least 20W and supports fast charging".
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any, Final

from sqlalchemy import CheckConstraint, ForeignKey, Index, String, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import CANONICAL_TOKEN_REGEX, Base, TimestampMixin, uuid_pk

if TYPE_CHECKING:
    from app.db.models.product import Product

#: How a product relates to its target (D§13, D§14; ADR-003).
#:
#: ``device`` is the broad form the specification uses for chargers, where the
#: target is an end device rather than specifically a phone or a laptop. A query
#: for "compatible with the phone iphone_16" therefore matches rules whose
#: target_type is in ('phone_model', 'device').
COMPATIBILITY_TARGET_TYPES: Final[tuple[str, ...]] = (
    "phone_model",
    "laptop_model",
    "device",
    "device_port",
)

#: ADR-003: only ``compatible`` is permitted in the MVP.
COMPATIBILITY_RULE_TYPES: Final[tuple[str, ...]] = ("compatible",)


def _sql_in_list(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{value}'" for value in values)


class CompatibilityRule(Base, TimestampMixin):
    __tablename__ = "compatibility_rules"
    __table_args__ = (
        # A product should not carry the same rule twice.
        UniqueConstraint(
            "product_id",
            "target_type",
            "target_identifier",
            "rule_type",
            name="uq_compatibility_rules_product_target",
        ),
        CheckConstraint(
            f"target_type IN ({_sql_in_list(COMPATIBILITY_TARGET_TYPES)})",
            name="target_type_is_known",
        ),
        CheckConstraint(
            f"target_identifier ~ '{CANONICAL_TOKEN_REGEX}'",
            name="target_identifier_is_canonical_token",
        ),
        CheckConstraint(
            f"rule_type IN ({_sql_in_list(COMPATIBILITY_RULE_TYPES)})",
            name="rule_type_is_supported",
        ),
        CheckConstraint("jsonb_typeof(constraints) = 'object'", name="constraints_is_object"),
        # D§24, verbatim: the index that makes "everything compatible with
        # iphone_16" a lookup rather than a scan (D§25).
        Index(
            "ix_compatibility_rules_target_type_target_identifier",
            "target_type",
            "target_identifier",
        ),
        Index("ix_compatibility_rules_product_id", "product_id"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    product_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("products.id", ondelete="CASCADE"),
        nullable=False,
    )
    target_type: Mapped[str] = mapped_column(String(64), nullable=False)
    target_identifier: Mapped[str] = mapped_column(String(128), nullable=False)
    rule_type: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default=text("'compatible'")
    )
    constraints: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )

    product: Mapped[Product] = relationship(back_populates="compatibility_rules")

    def __repr__(self) -> str:
        return f"<CompatibilityRule {self.target_type}={self.target_identifier!r}>"
