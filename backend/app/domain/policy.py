"""Policy inputs and outputs (P§5, P§7, ADR-011).

The Policy Engine's whole design rests on these being *values*. A
`TransactionContext` is a snapshot of live state that somebody else read, inside
a transaction, with the inventory rows locked; a `PolicyDecision` is a verdict
about it. Neither carries a session, a connection or a model, which is what lets
the engine be exhaustively unit-testable and what makes "the result is generated
by application code" (P§7) a checkable property rather than a hope.

**Every price and quantity in a context must be *live*.** The types cannot
enforce that — a `Decimal` read from a snapshot looks identical to one read from
`product_variants` — so the field names say where each value must come from, and
`OrderService` (M10) is the only code permitted to build one. RULE 12 and P§11
require the freshness; ADR-014's price-drift recovery depends on it.

`ReasonCode` is a closed list. P§7's example shows `reason_codes` as an array
because the buyer is told everything that is wrong in one message rather than
discovering problems one round-trip at a time.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Literal

__all__ = [
    "LineContext",
    "PolicyDecision",
    "ReasonCode",
    "TransactionContext",
]


class ReasonCode(StrEnum):
    """Why the Policy Engine refused (ADR-011).

    Machine-readable and stable: the frontend renders a recovery flow per code,
    so these are part of the contract rather than log text. Several rules share
    a code deliberately — a buyer does not need to know whether the *product* or
    the *variant* was deactivated, only that the item is no longer purchasable.
    """

    APPROVAL_REQUIRED = "APPROVAL_REQUIRED"
    INVALID_CART = "INVALID_CART"
    INVALID_PRODUCT = "INVALID_PRODUCT"
    PRICE_CHANGED = "PRICE_CHANGED"
    OUT_OF_STOCK = "OUT_OF_STOCK"
    SPENDING_LIMIT_EXCEEDED = "SPENDING_LIMIT_EXCEEDED"
    ORDER_ALREADY_EXISTS = "ORDER_ALREADY_EXISTS"


@dataclass(frozen=True, slots=True)
class LineContext:
    """One cart line, with the live facts about it.

    `unit_price` is the price read from `product_variants` at evaluation time —
    **never** `cart_items.unit_price_snapshot`. `available_quantity` is from the
    locked `inventory` row. The whole point of the engine is to compare what was
    approved against these, so a context built from snapshots would make every
    rule agree with itself.
    """

    variant_id: uuid.UUID
    product_id: uuid.UUID
    sku: str
    quantity: int
    #: Live, from `product_variants`.
    unit_price: Decimal
    currency: str
    #: Live, from the locked `inventory` row.
    available_quantity: int
    #: Both must be true for the line to be sellable (ADR-005 constraint 1).
    product_is_active: bool
    variant_is_active: bool
    #: Who owns the product. Carried so rule 3 can *check* merchant ownership
    #: rather than assume the query that loaded it was scoped correctly.
    merchant_id: uuid.UUID

    @property
    def line_total(self) -> Decimal:
        return self.unit_price * self.quantity


@dataclass(frozen=True, slots=True)
class TransactionContext:
    """Everything the engine needs, and nothing it would have to fetch.

    P§5 sketches this as a JSON document; ADR-011 says to implement it as typed
    backend models. Built by `OrderService` inside the order transaction, with
    the inventory rows locked, and by nothing else.
    """

    merchant_id: uuid.UUID
    session_id: uuid.UUID
    cart_id: uuid.UUID
    #: The version the client claimed. A claim to be checked, not an instruction.
    cart_version: int
    #: The cart's *current* version, from the row.
    current_cart_version: int
    cart_status: str
    currency: str
    lines: tuple[LineContext, ...]

    #: The approval, or `None` when there is none at all. `None` is the common
    #: failure and is distinct from an approval that exists and no longer holds.
    approval_id: uuid.UUID | None = None
    approval_status: str | None = None
    approval_cart_version: int | None = None
    approved_total: Decimal | None = None
    approval_currency: str | None = None
    approval_fingerprint: str | None = None
    approval_expires_at: datetime | None = None
    approval_superseded: bool = False
    #: The fingerprint recomputed from `lines` by the caller, using the one
    #: shared function in `app.domain.approval`.
    current_fingerprint: str | None = None

    #: Orders already existing for this cart that are not cancelled.
    existing_order_ids: tuple[uuid.UUID, ...] = ()
    #: `None` when the key is unused; a status string when it exists.
    idempotency_status: str | None = None
    idempotency_key_present: bool = False

    #: The instant the evaluation happens, passed in rather than read, so the
    #: engine stays pure and an expiry test does not have to sleep.
    evaluated_at: datetime | None = None

    @property
    def computed_total(self) -> Decimal:
        """The live total. What the buyer would actually be charged."""
        return sum((line.line_total for line in self.lines), Decimal("0.00"))


@dataclass(frozen=True, slots=True)
class PolicyDecision:
    """A deterministic verdict (P§7).

    `reason_codes` is empty if and only if the decision is PASS, and a test
    asserts that in both directions — a PASS with reasons or a FAIL without them
    would be a verdict nobody could act on.

    `validated_total` is present on a FAIL too, and deliberately: P§7's own
    example shows `PRICE_CHANGED` alongside `validated_total: 1998`, because the
    number the buyer must now be shown is exactly the one that caused the
    refusal.
    """

    decision: Literal["PASS", "FAIL"]
    validated_total: Decimal
    currency: str
    reason_codes: tuple[ReasonCode, ...] = ()
    #: Human-readable context per code, for the frontend to render. Never a
    #: stack trace, never a database message (F§25).
    details: dict[str, str] = field(default_factory=dict)

    @property
    def passed(self) -> bool:
        return self.decision == "PASS"

    def __post_init__(self) -> None:
        if (self.decision == "PASS") != (not self.reason_codes):
            raise ValueError("a PASS carries no reason codes and a FAIL carries at least one")
