"""Hard constraints. They eliminate; they never score (ADR-005).

D§15 states the failure this module exists to prevent, in the specification's
own arithmetic:

    incompatible product - very cheap price - good rating = high recommendation score
    That would be unsafe and logically incorrect.

So there is no weight, anywhere, that can be turned up far enough to let an
incompatible or out-of-stock product be recommended. Those products are not
scored low; they are not scored at all. R§17 RULE 3, RULE 4 and RULE 5 say the
same thing three ways.

One function per constraint, each callable and testable on its own, plus
`apply_hard_constraints` composing them in the order D§29 sets out. Order
matters for cost, not for correctness — the predicates commute — so the cheapest
and most eliminating run first.

Every candidate is evaluated against **every** constraint rather than stopping
at the first failure. Two reasons: the Policy Engine (M9) will do the same for
the same reason, and deciding whether a rejected product is an honest
*alternative* requires knowing it failed only a relaxable constraint (ADR-005).
A product rejected for both budget and compatibility must not look like a
budget-only near miss.
"""

from __future__ import annotations

import uuid
from collections.abc import Collection, Iterable, Mapping

from app.attributes import predicate_satisfied
from app.domain import (
    ConstraintFailure,
    FilterResult,
    HardConstraint,
    ProductRequirement,
    RejectedCandidate,
    StockStatus,
    StockView,
    VariantView,
)

__all__ = [
    "apply_hard_constraints",
    "check_budget",
    "check_category",
    "check_compatibility",
    "check_existence",
    "check_inventory",
    "check_merchant",
    "check_required_specification",
]


def check_existence(variant: VariantView) -> ConstraintFailure | None:
    """Constraint 1: the product and the variant are both active.

    An active variant of a deactivated product is not sellable. The repository
    already filters on both flags, and this re-checks rather than trusting it:
    `VariantQuery` can be asked for inactive rows, and a caller that did so and
    then ranked the result would be offering products the merchant withdrew.
    """
    if not variant.product_is_active:
        return ConstraintFailure(
            HardConstraint.EXISTENCE, f"product {variant.product_slug} is not active"
        )
    if not variant.is_active:
        return ConstraintFailure(HardConstraint.EXISTENCE, f"variant {variant.sku} is not active")
    return None


def check_merchant(variant: VariantView, merchant_id: uuid.UUID) -> ConstraintFailure | None:
    """Constraint 2: the variant belongs to the session's resolved merchant.

    ADR-002: the merchant is resolved server-side and never taken from model
    output or a request body. This is defence in depth — every repository query
    is already scoped — because a cross-merchant leak would otherwise be silent,
    and silence is the whole problem with that class of bug.
    """
    if variant.merchant_id != merchant_id:
        return ConstraintFailure(
            HardConstraint.MERCHANT, f"variant {variant.sku} belongs to another merchant"
        )
    return None


def check_category(
    variant: VariantView, requirement: ProductRequirement
) -> ConstraintFailure | None:
    """Constraint 3: the product is of the type that was asked for.

    Skipped when the buyer named no category — an unnamed category is not a
    constraint, and treating it as one would return nothing at all.
    """
    if requirement.category_slug is None:
        return None
    if variant.category_slug != requirement.category_slug:
        return ConstraintFailure(
            HardConstraint.CATEGORY,
            f"category {variant.category_slug} is not {requirement.category_slug}",
        )
    return None


def check_budget(variant: VariantView, requirement: ProductRequirement) -> ConstraintFailure | None:
    """Constraint 4: `price <= max_budget` (R§8, D§30).

    Hard, not soft. A product ₹1 over budget is removed, not ranked slightly
    lower. When that removes everything, the honest recovery is the
    `NO_MATCH_WITH_ALTERNATIVES` outcome, which names the product *and* says it
    is over budget — not a quiet widening of the ceiling.
    """
    if requirement.max_price is None:
        return None
    if variant.price > requirement.max_price:
        return ConstraintFailure(
            HardConstraint.BUDGET,
            f"price {variant.price} exceeds budget {requirement.max_price}",
        )
    return None


def check_compatibility(
    variant: VariantView, compatible_product_ids: Collection[uuid.UUID] | None
) -> ConstraintFailure | None:
    """Constraint 5: a compatibility rule exists for the resolved target.

    `compatible_product_ids` is computed by `CompatibilityService` against the
    **canonical** identifier and with the rule's own `constraints` predicates
    already evaluated (ADR-003). This function only reads the answer; it does no
    matching of its own, and there is deliberately no substring or fallback path
    here for it to reach for.

    `None` means the buyer stated no compatibility requirement.
    `apply_hard_constraints` refuses to accept `None` when the requirement does
    carry a target, so "the caller forgot to resolve compatibility" can never be
    mistaken for "compatibility does not apply".
    """
    if compatible_product_ids is None:
        return None
    if variant.product_id not in compatible_product_ids:
        return ConstraintFailure(
            HardConstraint.COMPATIBILITY,
            f"product {variant.product_slug} has no compatibility rule for the requested device",
        )
    return None


def check_required_specification(
    variant: VariantView, requirement: ProductRequirement
) -> ConstraintFailure | None:
    """Constraint 6: attributes the buyer stated as requirements, not wishes.

    "Must be fast charging", "must be USB-C". The classification comes from the
    intent schema's two separate fields, never from heuristics over phrasing
    (ADR-005): `required_attributes` eliminates, `preferences` scores. Where the
    model is unsure, the safe placement is `preferences`, because over-filtering
    hides real products silently while under-filtering merely reorders them.

    The predicate forms are the ones `app.attributes` defines, identical to
    those a compatibility rule uses, so "at least 20W" means the same thing
    wherever it is written.
    """
    for key, expected in requirement.required_attributes.items():
        if not predicate_satisfied(variant.merged_attributes, key, expected):
            return ConstraintFailure(
                HardConstraint.REQUIRED_SPECIFICATION,
                f"{key}={expected!r} is not satisfied by {variant.sku}",
            )
    return None


def check_inventory(
    variant: VariantView, stock: StockView | None, quantity: int
) -> ConstraintFailure | None:
    """Constraint 7: `available >= requested` (D§11, D§29 step 6).

    RULE 5 and R§6: "Compatible + Out of Stock ≠ Purchasable". Out-of-stock
    products are removed, never ranked low.

    A variant with no stock record is rejected, not assumed available. The schema
    permits the row to be absent, an absent row is strictly less information than
    a recorded zero, and this is the direction that fails closed.

    The filter here is a courtesy to the buyer, not a guarantee: stock is
    re-checked at cart time and again by the Policy Engine inside the order
    transaction (RULE 12, ADR-011).
    """
    if stock is None:
        return ConstraintFailure(HardConstraint.INVENTORY, f"no inventory record for {variant.sku}")
    if stock.available_quantity < quantity:
        detail = (
            f"{stock.available_quantity} available, {quantity} requested"
            if stock.status is not StockStatus.NO_RECORD
            else f"no inventory record for {variant.sku}"
        )
        return ConstraintFailure(HardConstraint.INVENTORY, detail)
    return None


def apply_hard_constraints(
    candidates: Iterable[VariantView],
    requirement: ProductRequirement,
    *,
    merchant_id: uuid.UUID,
    stock: Mapping[uuid.UUID, StockView],
    compatible_product_ids: Collection[uuid.UUID] | None = None,
) -> FilterResult:
    """Apply all seven constraints, in D§29 order, recording every failure.

    Raises `ValueError` when the requirement carries a compatibility target but
    no compatible-product set was supplied. That combination can only mean the
    caller skipped compatibility resolution, and the alternative — treating it as
    "no compatibility requirement" — would let every incompatible product
    through while looking like a normal empty-constraint case. Compatibility is
    the one constraint that is never relaxed, so it must not be relaxable by
    omission either.
    """
    if requirement.compatibility_target is not None and compatible_product_ids is None:
        raise ValueError(
            "requirement carries a compatibility target "
            f"({requirement.compatibility_target.canonical_identifier!r}) but no "
            "compatible_product_ids were supplied; resolve compatibility before ranking (ADR-003)"
        )

    survivors: list[VariantView] = []
    rejected: list[RejectedCandidate] = []

    for variant in candidates:
        failures = tuple(
            failure
            for failure in (
                check_existence(variant),
                check_merchant(variant, merchant_id),
                check_category(variant, requirement),
                check_budget(variant, requirement),
                check_compatibility(variant, compatible_product_ids),
                check_required_specification(variant, requirement),
                check_inventory(variant, stock.get(variant.id), requirement.quantity),
            )
            if failure is not None
        )
        if failures:
            rejected.append(RejectedCandidate(variant=variant, failures=failures))
        else:
            survivors.append(variant)

    return FilterResult(survivors=tuple(survivors), rejected=tuple(rejected))
