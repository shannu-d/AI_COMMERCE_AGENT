"""The merchant activity vocabulary — who changed the catalogue, and to what.

**Deliberately not `audit_events`.** That table answers "how did *this
transaction* reach its outcome": it hangs off a session, a cart, an order or a
payment, and its vocabulary is the money path's twelve RZP-07 events plus four
failure cases. A price edit has none of those anchors and belongs to none of
that story. Folding merchant administration into it would mean widening two
`CHECK` constraints and adding two columns that are null for every existing row,
and would leave one log answering two unrelated questions — the reconstruction
of a purchase would then have to be filtered out of a stream of stock edits.

So merchant activity is its own append-only log, with its own closed
vocabulary, and the two never need to agree about anything.

**What it is for.** A merchant dashboard mutates the catalogue that the agent
then recommends from. When a buyer is quoted a price nobody expected, the
question is *who set it and when*, and only a record written at the moment of
the change can answer that. `payload` carries the before-and-after of what
changed, so the answer does not depend on the row still being there.
"""

from __future__ import annotations

from enum import StrEnum

__all__ = [
    "MERCHANT_ACTIONS",
    "MERCHANT_ENTITY_TYPES",
    "MerchantAction",
    "MerchantEntityType",
]


class MerchantAction(StrEnum):
    """What an administrator did.

    Closed, and rendered into a `CHECK` constraint: an action nobody named is a
    write nobody reviewed. Reads are absent on purpose — logging every list
    request would bury the eleven writes that can actually change what a buyer
    is offered.
    """

    PRODUCT_CREATED = "PRODUCT_CREATED"
    PRODUCT_UPDATED = "PRODUCT_UPDATED"
    PRODUCT_ARCHIVED = "PRODUCT_ARCHIVED"
    PRODUCT_RESTORED = "PRODUCT_RESTORED"
    VARIANT_CREATED = "VARIANT_CREATED"
    VARIANT_UPDATED = "VARIANT_UPDATED"
    VARIANT_ARCHIVED = "VARIANT_ARCHIVED"
    VARIANT_RESTORED = "VARIANT_RESTORED"
    PRICE_CHANGED = "PRICE_CHANGED"
    STOCK_CHANGED = "STOCK_CHANGED"
    CATEGORY_CREATED = "CATEGORY_CREATED"


class MerchantEntityType(StrEnum):
    """What the action was done to."""

    PRODUCT = "PRODUCT"
    VARIANT = "VARIANT"
    CATEGORY = "CATEGORY"


def _values(enum: type[StrEnum]) -> tuple[str, ...]:
    return tuple(member.value for member in enum)


#: The tuples migration `0006` renders into `CHECK` constraints, kept beside the
#: enums so a new member reaches the database in the same edit.
MERCHANT_ACTIONS = _values(MerchantAction)
MERCHANT_ENTITY_TYPES = _values(MerchantEntityType)
