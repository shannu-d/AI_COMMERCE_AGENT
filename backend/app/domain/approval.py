"""Approval domain values and the items fingerprint (ADR-007, P§10, A§26).

**`items_fingerprint` is defined here and nowhere else.** ADR-007 requires one
shared implementation used by both the writer and the Policy Engine, because a
second one would eventually disagree with the first — and the disagreement would
present as an approval that silently stops matching its own cart.

It exists because *a total is not a composition*. Two different carts can reach
₹1,798: a ₹1,499 case plus a ₹299 guard, or a ₹1,299 case plus a ₹499 twin-pack.
The total is identical and the order is completely different. `cart_version`
catches that in the normal case; the fingerprint catches it unconditionally.

The serialization is canonical on purpose — sorted by `variant_id`, amounts as
fixed-scale strings, separators without whitespace. Any of those left loose and
the same cart would fingerprint differently on two machines, or after a Python
upgrade, and every existing approval would go stale at once.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum

from app.domain.commerce import ApprovalStatus

__all__ = [
    "ApprovalFailure",
    "ApprovalView",
    "FingerprintLine",
    "items_fingerprint",
]

_SCALE = Decimal("0.01")


@dataclass(frozen=True, slots=True)
class FingerprintLine:
    """The three facts about a line that an approval is a claim about."""

    variant_id: uuid.UUID
    quantity: int
    unit_price: Decimal


def items_fingerprint(lines: Iterable[FingerprintLine]) -> str:
    """SHA-256 over the canonical `(variant_id, quantity, unit_price)` list.

    Sorted by `variant_id` so the order lines were added in cannot change the
    digest. Amounts are rendered at fixed scale, so `Decimal("999")` and
    `Decimal("999.00")` — equal numbers, different reprs — cannot produce two
    fingerprints for one cart.
    """
    canonical = [
        [str(line.variant_id), line.quantity, str(line.unit_price.quantize(_SCALE))]
        for line in sorted(lines, key=lambda line: str(line.variant_id))
    ]
    encoded = json.dumps(canonical, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


class ApprovalFailure(StrEnum):
    """Why an approval could not be created or could not be used.

    Distinct values rather than one "invalid", because each calls for a
    different next action by the buyer: re-read the cart, re-approve, or start
    again.
    """

    #: The buyer approved a version that is no longer the cart's. ADR-007's
    #: named M8 exit test.
    CART_VERSION_STALE = "CART_VERSION_STALE"
    #: The composition changed while the version did not — the case the
    #: fingerprint exists to catch.
    ITEMS_CHANGED = "ITEMS_CHANGED"
    #: The total the buyer saw is not the total the cart now computes.
    TOTAL_CHANGED = "TOTAL_CHANGED"
    CART_NOT_FOUND = "CART_NOT_FOUND"
    CART_EMPTY = "CART_EMPTY"
    #: The TTL elapsed before the approval was used (ADR-007: 15 minutes).
    EXPIRED = "EXPIRED"
    #: A later approval, or a cart change, replaced it.
    SUPERSEDED = "SUPERSEDED"
    #: There is no approval at all for what was attempted.
    NOT_APPROVED = "NOT_APPROVED"


@dataclass(frozen=True, slots=True)
class ApprovalView:
    """One approval, detached from its row.

    Carries everything the Policy Engine needs to decide whether this claim
    still holds, and nothing it would have to trust the caller for.
    """

    id: uuid.UUID
    session_id: uuid.UUID
    cart_id: uuid.UUID
    cart_version: int
    approved_total: Decimal
    currency: str
    items_fingerprint: str
    status: ApprovalStatus
    created_at: datetime
    approved_at: datetime | None
    expires_at: datetime
    superseded_by_id: uuid.UUID | None = None

    def is_expired_at(self, now: datetime) -> bool:
        """Expiry is evaluated at the moment of use (ADR-007).

        A sweeper job is an optimization, never the mechanism: an approval that
        expired while nobody was looking must still be refused when it is used.
        """
        return now >= self.expires_at

    def authorizes(self, now: datetime) -> bool:
        """Whether this row authorizes anything at all, right now.

        Only `APPROVED`, unexpired and un-superseded. `PENDING` authorizes
        nothing — it records that the agent asked, not that the buyer answered.
        """
        return (
            self.status is ApprovalStatus.APPROVED
            and self.superseded_by_id is None
            and not self.is_expired_at(now)
        )


def lines_from(items: Sequence) -> list[FingerprintLine]:
    """`FingerprintLine`s from anything carrying the three fields.

    Takes `CartItemView`s in practice, but typed loosely so the Policy Engine
    can fingerprint order lines with the same function rather than a second one.
    """
    return [
        FingerprintLine(
            variant_id=item.variant_id, quantity=item.quantity, unit_price=item.unit_price
        )
        for item in items
    ]
