"""Inventory, always joined through the variant so it stays merchant-scoped.

`inventory` carries no `merchant_id` — it hangs off `product_variants`, which
does. Reading it without that join would cross merchant boundaries, so every
method here joins.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Inventory, ProductVariant


class InventoryRepository:
    """Reads from `inventory`."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def get_for_variant(self, merchant_id: uuid.UUID, variant_id: uuid.UUID) -> Inventory | None:
        """The inventory row, or `None` when the variant has none.

        `None` is a real outcome, not just an error path: the schema permits a
        variant with no inventory row, and the service distinguishes that from a
        recorded zero.
        """
        return self._session.execute(
            select(Inventory)
            .join(ProductVariant, ProductVariant.id == Inventory.variant_id)
            .where(
                Inventory.variant_id == variant_id,
                ProductVariant.merchant_id == merchant_id,
            )
        ).scalar_one_or_none()

    def get_for_variants(
        self, merchant_id: uuid.UUID, variant_ids: Sequence[uuid.UUID]
    ) -> dict[uuid.UUID, Inventory]:
        """Batch lookup, keyed by variant.

        One query for a whole candidate set rather than one per candidate: the
        recommendation pipeline checks stock for everything that survived the
        earlier filters (D§29 step 6), and N+1 there would be a query per SKU.

        A variant with no inventory row is simply absent from the mapping; the
        caller decides what that means.
        """
        if not variant_ids:
            return {}
        rows = (
            self._session.execute(
                select(Inventory)
                .join(ProductVariant, ProductVariant.id == Inventory.variant_id)
                .where(
                    Inventory.variant_id.in_(variant_ids),
                    ProductVariant.merchant_id == merchant_id,
                )
            )
            .scalars()
            .all()
        )
        return {row.variant_id: row for row in rows}
