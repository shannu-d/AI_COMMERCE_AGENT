"""Inventory domain types.

``available = quantity - reserved_quantity`` (architecture.md D§11). For the MVP
nothing writes ``reserved_quantity``; it stays at 0 (ADR-005).

``NO_RECORD`` exists because the schema genuinely permits a variant with no
inventory row — `inventory` holds a foreign key to `product_variants`, not the
reverse, so nothing forces the row to exist. The seed always creates one, but
a variant added by any other path might not have one, and the difference between
"we know there are none" and "we have no idea" must not be silently flattened.
Both are unpurchasable; only one of them is a data problem worth logging.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from enum import StrEnum


class StockStatus(StrEnum):
    """Coarse availability, as disclosed to the buyer (ADR-009, ADR-010).

    Exact quantities stay inside the services and the Policy Engine; the
    buyer-facing payload carries this instead (closing open question E5).
    """

    IN_STOCK = "IN_STOCK"
    LOW_STOCK = "LOW_STOCK"
    OUT_OF_STOCK = "OUT_OF_STOCK"
    #: No inventory row exists for this variant. Treated as unpurchasable.
    NO_RECORD = "NO_RECORD"


@dataclass(frozen=True, slots=True)
class StockView:
    """Authoritative stock for one variant, read from PostgreSQL."""

    variant_id: uuid.UUID
    quantity: int
    reserved_quantity: int
    status: StockStatus

    @property
    def available_quantity(self) -> int:
        """D§11. Never negative — a CHECK constraint enforces that."""
        return self.quantity - self.reserved_quantity

    @property
    def is_purchasable(self) -> bool:
        """Whether *any* quantity can be bought at all.

        `NO_RECORD` and `OUT_OF_STOCK` are both false. Failing closed is
        deliberate: the pre-submission gate requires out-of-stock products to be
        safely blocked, and an absent row is strictly less information than a
        zero.
        """
        return self.available_quantity > 0

    @classmethod
    def missing(cls, variant_id: uuid.UUID) -> StockView:
        """The view for a variant that has no inventory row."""
        return cls(
            variant_id=variant_id,
            quantity=0,
            reserved_quantity=0,
            status=StockStatus.NO_RECORD,
        )


@dataclass(frozen=True, slots=True)
class AvailabilityCheck:
    """The answer to "can I have N of this?"."""

    variant_id: uuid.UUID
    requested_quantity: int
    available_quantity: int
    status: StockStatus
    available: bool

    @property
    def shortfall(self) -> int:
        """How many short the request is; 0 when it can be satisfied."""
        return max(0, self.requested_quantity - self.available_quantity)
