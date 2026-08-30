"""Inventory Service — authoritative availability.

architecture.md A§21: availability, quantity validation, and the pre-order
re-check. M2 implements the first two; the pre-order re-check runs inside the
Policy Engine's transaction (ADR-011) and belongs to M9.

The rule this service enforces is the pre-submission gate item quoted in
`docs/notes/external-brief-gap.md` (PG-1): *out-of-stock products must be safely
blocked.* RULE 5 and R§6 put it the other way round — "Compatible + Out of Stock
≠ Purchasable". Stock eliminates; it never merely lowers a score (ADR-005).

**No reservation behaviour here.** `reserved_quantity` is read and stays at 0
for the MVP; nothing reserves, releases or expires (ADR-005, open question C5).
The reservation lifecycle belongs to the commerce milestones.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Sequence

from sqlalchemy.orm import Session

from app.config import get_settings
from app.domain import AvailabilityCheck, StockStatus, StockView
from app.repositories import InventoryRepository
from app.services._mapping import to_stock_view

logger = logging.getLogger(__name__)


class InventoryService:
    """Reads authoritative stock. Never writes, never estimates."""

    def __init__(self, session: Session, *, low_stock_threshold: int | None = None) -> None:
        self._repository = InventoryRepository(session)
        self._low_stock_threshold = (
            low_stock_threshold
            if low_stock_threshold is not None
            else get_settings().low_stock_threshold
        )

    # -- reads ---------------------------------------------------------------

    def get_stock(self, merchant_id: uuid.UUID, variant_id: uuid.UUID) -> StockView:
        """Stock for one variant. Always returns a view, never `None`.

        A variant with no inventory row yields `StockStatus.NO_RECORD` with zero
        available, rather than an exception or a `None` a caller might treat as
        "fine". The schema permits that row to be absent, and an absent row is
        strictly less information than a recorded zero — so it fails closed and
        is logged, because it is a data problem rather than a normal state.
        """
        inventory = self._repository.get_for_variant(merchant_id, variant_id)
        if inventory is None:
            logger.warning(
                "variant has no inventory record; treating as unpurchasable",
                extra={"variant_id": str(variant_id)},
            )
            return StockView.missing(variant_id)
        return to_stock_view(inventory, low_stock_threshold=self._low_stock_threshold)

    def get_stock_map(
        self, merchant_id: uuid.UUID, variant_ids: Sequence[uuid.UUID]
    ) -> dict[uuid.UUID, StockView]:
        """Stock for many variants in one query.

        Every requested id appears in the result, so a caller iterating a
        candidate set never has to decide what a missing key means — variants
        without an inventory row get a `NO_RECORD` view.
        """
        if not variant_ids:
            return {}
        found = self._repository.get_for_variants(merchant_id, variant_ids)
        return {
            variant_id: (
                to_stock_view(found[variant_id], low_stock_threshold=self._low_stock_threshold)
                if variant_id in found
                else StockView.missing(variant_id)
            )
            for variant_id in variant_ids
        }

    # -- checks --------------------------------------------------------------

    def check_availability(
        self, merchant_id: uuid.UUID, variant_id: uuid.UUID, quantity: int = 1
    ) -> AvailabilityCheck:
        """Can this merchant sell `quantity` of this variant right now?

        The comparison is `available >= requested`, per D§29 step 6 — enough
        stock for the requested quantity, not merely non-zero.
        """
        if quantity < 1:
            raise ValueError("quantity must be at least 1")

        stock = self.get_stock(merchant_id, variant_id)
        available = stock.available_quantity
        return AvailabilityCheck(
            variant_id=variant_id,
            requested_quantity=quantity,
            available_quantity=available,
            status=stock.status,
            available=available >= quantity,
        )

    def is_available(
        self, merchant_id: uuid.UUID, variant_id: uuid.UUID, quantity: int = 1
    ) -> bool:
        return self.check_availability(merchant_id, variant_id, quantity).available

    def filter_available(
        self,
        merchant_id: uuid.UUID,
        variant_ids: Sequence[uuid.UUID],
        quantity: int = 1,
    ) -> list[uuid.UUID]:
        """Keep only variants with enough stock, preserving the input order.

        Order is preserved so a deterministic ordering established upstream
        survives the filter (R§8).
        """
        if quantity < 1:
            raise ValueError("quantity must be at least 1")
        stock_map = self.get_stock_map(merchant_id, variant_ids)
        return [
            variant_id
            for variant_id in variant_ids
            if stock_map[variant_id].available_quantity >= quantity
        ]

    def stock_status(self, merchant_id: uuid.UUID, variant_id: uuid.UUID) -> StockStatus:
        """The coarse status disclosed to the buyer (ADR-009, ADR-010)."""
        return self.get_stock(merchant_id, variant_id).status
