"""Hard constraints eliminate. They never demote.

One test per constraint, each proving the candidate is *absent* from the
survivors rather than present with a lower score — because D§15 names the
failure precisely:

    incompatible product - very cheap price - good rating = high recommendation score
    That would be unsafe and logically incorrect.

The last test in this file is the one that matters most: a cheaper incompatible
product cannot win under *any* weight profile, because it never reaches the
scorer at all.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest

from app.domain import HardConstraint, ProductRequirement, ResolvedTarget, StockStatus, StockView
from app.ranking.filters import (
    apply_hard_constraints,
    check_budget,
    check_category,
    check_compatibility,
    check_existence,
    check_inventory,
    check_merchant,
    check_required_specification,
)
from tests.ranking.conftest import (
    MERCHANT_ID,
    OTHER_MERCHANT_ID,
    make_variant,
    out_of_stock,
    stock_for,
)


def filter_all(candidates, requirement, *, stock=None, compatible=None, merchant=MERCHANT_ID):
    """Run the whole filter with everything in stock unless told otherwise."""
    return apply_hard_constraints(
        candidates,
        requirement,
        merchant_id=merchant,
        stock=stock if stock is not None else stock_for(candidates),
        compatible_product_ids=compatible,
    )


def skus(variants) -> set[str]:
    return {v.sku for v in variants}


# --------------------------------------------------------------------------
# 1. Existence and activity
# --------------------------------------------------------------------------


def test_an_inactive_variant_is_removed() -> None:
    variant = make_variant("DEAD", "999.00", is_active=False)

    assert check_existence(variant) is not None
    assert check_existence(variant).constraint is HardConstraint.EXISTENCE


def test_an_active_variant_of_an_inactive_product_is_removed() -> None:
    """A live variant of a withdrawn product is not sellable."""
    variant = make_variant("ORPHAN", "999.00", product_is_active=False)

    assert check_existence(variant) is not None


def test_an_active_variant_passes() -> None:
    assert check_existence(make_variant("LIVE", "999.00")) is None


def test_inactive_candidates_never_reach_the_survivors() -> None:
    """The repository already filters these; the ranker re-checks, because
    `VariantQuery` can be asked for inactive rows and a caller that did so
    would otherwise be offering products the merchant withdrew."""
    live = make_variant("LIVE", "999.00")
    dead = make_variant("DEAD", "499.00", is_active=False)
    requirement = ProductRequirement(label="phone_case")

    result = filter_all([live, dead], requirement)

    assert skus(result.survivors) == {"LIVE"}


# --------------------------------------------------------------------------
# 2. Merchant (ADR-002)
# --------------------------------------------------------------------------


def test_another_merchants_variant_is_removed() -> None:
    variant = make_variant("FOREIGN", "999.00", merchant_id=OTHER_MERCHANT_ID)

    failure = check_merchant(variant, MERCHANT_ID)

    assert failure is not None
    assert failure.constraint is HardConstraint.MERCHANT


def test_merchant_scoping_excludes_rather_than_reorders() -> None:
    """Defence in depth. Every repository query is already scoped; a leak here
    would be silent, which is the whole problem with that class of bug."""
    ours = make_variant("OURS", "1299.00")
    theirs = make_variant("THEIRS", "199.00", merchant_id=OTHER_MERCHANT_ID)
    requirement = ProductRequirement(label="phone_case")

    result = filter_all([ours, theirs], requirement)

    assert skus(result.survivors) == {"OURS"}
    assert HardConstraint.MERCHANT in result.rejected[0].constraints


# --------------------------------------------------------------------------
# 3. Category
# --------------------------------------------------------------------------


def test_a_product_of_the_wrong_type_is_removed() -> None:
    charger = make_variant("CHG", "1099.00", category_slug="charger")
    requirement = ProductRequirement(label="phone_case", category_slug="phone_case")

    assert check_category(charger, requirement) is not None


def test_no_stated_category_constrains_nothing() -> None:
    """An unnamed category is not a constraint; treating it as one returns nothing."""
    charger = make_variant("CHG", "1099.00", category_slug="charger")

    assert check_category(charger, ProductRequirement(label="anything")) is None


# --------------------------------------------------------------------------
# 4. Budget (R§8, D§30)
# --------------------------------------------------------------------------


def test_a_product_over_budget_is_removed_not_ranked_low() -> None:
    """R§8's own example: budget ₹1,500, anything above it is REJECT."""
    folio = make_variant("LTR", "1799.00")
    requirement = ProductRequirement(label="phone_case", max_price=Decimal("1500"))

    failure = check_budget(folio, requirement)

    assert failure is not None
    assert failure.constraint is HardConstraint.BUDGET


def test_a_product_exactly_at_the_budget_survives() -> None:
    """`price <= max_budget`. At the line is inside it."""
    variant = make_variant("EXACT", "1500.00")
    requirement = ProductRequirement(label="phone_case", max_price=Decimal("1500"))

    assert check_budget(variant, requirement) is None


def test_one_rupee_over_budget_is_still_over() -> None:
    variant = make_variant("OVER", "1500.01")
    requirement = ProductRequirement(label="phone_case", max_price=Decimal("1500"))

    assert check_budget(variant, requirement) is not None


def test_the_budget_failure_names_both_numbers() -> None:
    """The agent has to be able to say *why*, without re-deriving it."""
    variant = make_variant("OVER", "1799.00")
    requirement = ProductRequirement(label="phone_case", max_price=Decimal("1500"))

    detail = check_budget(variant, requirement).detail

    assert "1799.00" in detail and "1500" in detail


# --------------------------------------------------------------------------
# 5. Compatibility (ADR-003, ADR-005)
# --------------------------------------------------------------------------


def test_a_product_with_no_compatibility_rule_is_removed(iphone_15_case) -> None:
    failure = check_compatibility(iphone_15_case, set())

    assert failure is not None
    assert failure.constraint is HardConstraint.COMPATIBILITY


def test_no_stated_device_means_compatibility_does_not_apply(iphone_15_case) -> None:
    assert check_compatibility(iphone_15_case, None) is None


def test_a_requirement_with_a_target_but_no_resolved_set_is_a_loud_error(
    aerocase, iphone_16
) -> None:
    """The one place `None` would be catastrophic.

    Treating "the caller forgot to resolve compatibility" as "compatibility does
    not apply" would let every incompatible product through while looking like a
    perfectly ordinary unconstrained search. Compatibility is never relaxed, so
    it must not be relaxable by omission either.
    """
    requirement = ProductRequirement(label="phone_case", compatibility_target=iphone_16)

    with pytest.raises(ValueError, match="resolve compatibility before ranking"):
        apply_hard_constraints(
            [aerocase],
            requirement,
            merchant_id=MERCHANT_ID,
            stock=stock_for([aerocase]),
            compatible_product_ids=None,
        )


def test_a_resolvable_device_with_nothing_compatible_yields_no_survivors(
    aerocase, iphone_16
) -> None:
    """R§14's Pixel 9 case: the device was understood, the catalog has nothing.

    An empty compatible set is a legitimate answer, and it is not the same fact
    as an unresolvable device — which never reaches this layer at all (ADR-003).
    """
    requirement = ProductRequirement(label="phone_case", compatibility_target=iphone_16)

    result = filter_all([aerocase], requirement, compatible=set())

    assert result.survivors == ()
    assert HardConstraint.COMPATIBILITY in result.rejected[0].constraints


# --------------------------------------------------------------------------
# 6. Required specification (ADR-005)
# --------------------------------------------------------------------------


def test_a_stated_requirement_eliminates() -> None:
    """ "Must be USB-C" removes; it does not merely score lower."""
    variant = make_variant("MICRO", "299.00", product_attributes={"port_type": "micro_usb"})
    requirement = ProductRequirement(label="cable", required_attributes={"port_type": "usb_c"})

    failure = check_required_specification(variant, requirement)

    assert failure is not None
    assert failure.constraint is HardConstraint.REQUIRED_SPECIFICATION


def test_a_requirement_is_checked_against_merged_attributes() -> None:
    """D§27: the variant's own attributes win over its product's."""
    variant = make_variant(
        "VAR",
        "299.00",
        product_attributes={"port_type": "micro_usb"},
        attributes={"port_type": "usb_c"},
    )
    requirement = ProductRequirement(label="cable", required_attributes={"port_type": "usb_c"})

    assert check_required_specification(variant, requirement) is None


def test_requirements_use_the_same_predicate_forms_as_compatibility_rules() -> None:
    """`app.attributes` is shared, so "at least 20W" means one thing everywhere."""
    charger = make_variant("C30", "1499.00", product_attributes={"wattage": 30})
    weak = make_variant("C18", "999.00", product_attributes={"wattage": 18})
    requirement = ProductRequirement(label="charger", required_attributes={"minimum_wattage": 20})

    assert check_required_specification(charger, requirement) is None
    assert check_required_specification(weak, requirement) is not None


def test_a_missing_attribute_fails_the_requirement() -> None:
    """The catalog cannot evidence it, so it has not been shown to hold."""
    variant = make_variant("PLAIN", "299.00")
    requirement = ProductRequirement(label="cable", required_attributes={"port_type": "usb_c"})

    assert check_required_specification(variant, requirement) is not None


def test_a_preference_never_eliminates() -> None:
    """The whole ADR-005 asymmetry in one assertion: the same key/value pair
    removes a product as a requirement and merely reorders it as a preference."""
    variant = make_variant("BLUE", "999.00", attributes={"color": "blue"})
    as_requirement = ProductRequirement(label="c", required_attributes={"color": "black"})
    as_preference = ProductRequirement(label="c", preferences={"color": "black"})

    assert filter_all([variant], as_requirement).survivors == ()
    assert skus(filter_all([variant], as_preference).survivors) == {"BLUE"}


# --------------------------------------------------------------------------
# 7. Inventory (RULE 5, D§11)
# --------------------------------------------------------------------------


def test_an_out_of_stock_variant_is_removed() -> None:
    """RULE 5 and R§6: "Compatible + Out of Stock ≠ Purchasable"."""
    variant = make_variant("CLR", "949.00")

    failure = check_inventory(variant, out_of_stock(variant), 1)

    assert failure is not None
    assert failure.constraint is HardConstraint.INVENTORY


def test_insufficient_stock_for_the_requested_quantity_is_removed() -> None:
    """D§29 step 6: `available >= requested`, not merely non-zero."""
    variant = make_variant("LOW", "999.00")
    stock = StockView(
        variant_id=variant.id, quantity=2, reserved_quantity=0, status=StockStatus.LOW_STOCK
    )

    assert check_inventory(variant, stock, 1) is None
    assert check_inventory(variant, stock, 3) is not None


def test_reserved_quantity_reduces_what_is_available() -> None:
    """D§11: `available = quantity - reserved_quantity`. Nothing writes
    `reserved_quantity` in the MVP, but the arithmetic is the schema's."""
    variant = make_variant("RES", "999.00")
    stock = StockView(
        variant_id=variant.id, quantity=5, reserved_quantity=5, status=StockStatus.OUT_OF_STOCK
    )

    assert check_inventory(variant, stock, 1) is not None


def test_a_variant_with_no_inventory_row_is_removed_not_assumed_available() -> None:
    """An absent row is strictly less information than a recorded zero, so this
    fails closed."""
    variant = make_variant("NOROW", "999.00")

    failure = check_inventory(variant, None, 1)

    assert failure is not None
    assert "no inventory record" in failure.detail


def test_a_missing_stock_entry_eliminates_through_the_composed_filter() -> None:
    present = make_variant("HAS", "999.00")
    absent = make_variant("NONE", "499.00")
    requirement = ProductRequirement(label="phone_case")

    result = filter_all(
        [present, absent], requirement, stock=stock_for([present, absent], missing=["NONE"])
    )

    assert skus(result.survivors) == {"HAS"}


# --------------------------------------------------------------------------
# The composed filter
# --------------------------------------------------------------------------


def test_every_failure_is_recorded_not_just_the_first(iphone_16) -> None:
    """Deciding whether a product is an honest alternative needs all of them:
    one rejected for budget *and* compatibility is not a budget-only near miss."""
    variant = make_variant("BOTH", "1799.00")
    requirement = ProductRequirement(
        label="phone_case", max_price=Decimal("1500"), compatibility_target=iphone_16
    )

    result = filter_all([variant], requirement, compatible=set())

    assert result.rejected[0].constraints == {
        HardConstraint.BUDGET,
        HardConstraint.COMPATIBILITY,
    }


def test_the_primary_failure_follows_the_d29_evaluation_order(iphone_16) -> None:
    """D§29: category, budget, compatibility, specification, inventory."""
    variant = make_variant("MANY", "1799.00", category_slug="charger")
    requirement = ProductRequirement(
        label="phone_case",
        category_slug="phone_case",
        max_price=Decimal("1500"),
        compatibility_target=iphone_16,
    )

    rejected = filter_all([variant], requirement, compatible=set()).rejected[0]

    assert rejected.primary.constraint is HardConstraint.CATEGORY


def test_survivors_keep_the_order_they_arrived_in() -> None:
    """The repository orders by (price, sku); the filter must not disturb it, so
    that a deterministic ordering established upstream survives (RULE 8)."""
    variants = [make_variant(f"SKU-{i}", f"{100 * i}.00") for i in range(1, 6)]
    requirement = ProductRequirement(label="phone_case")

    result = filter_all(variants, requirement)

    assert [v.sku for v in result.survivors] == [v.sku for v in variants]


def test_rejected_by_selects_a_single_constraint(iphone_16) -> None:
    over_budget = make_variant("OVER", "1799.00")
    incompatible = make_variant("INCOMPAT", "999.00")
    requirement = ProductRequirement(
        label="phone_case", max_price=Decimal("1500"), compatibility_target=iphone_16
    )

    result = filter_all([over_budget, incompatible], requirement, compatible=set())

    assert skus(v.variant for v in result.rejected_by(HardConstraint.BUDGET)) == {"OVER"}


def test_only_budget_and_specification_are_relaxable(iphone_16) -> None:
    """ADR-005 with RULE 5 added: compatibility is never relaxed, and neither is
    inventory, because an alternative nobody can buy is not an alternative."""
    over_budget = make_variant("OVER", "1799.00")
    incompatible = make_variant("INCOMPAT", "999.00", product_slug="other")
    requirement = ProductRequirement(
        label="phone_case", max_price=Decimal("1500"), compatibility_target=iphone_16
    )

    result = filter_all(
        [over_budget, incompatible],
        requirement,
        compatible={over_budget.product_id},
    )

    assert skus(r.variant for r in result.relaxable_rejections) == {"OVER"}


def test_an_out_of_stock_product_is_never_offered_as_an_alternative() -> None:
    """RULE 5 again, from the other direction."""
    variant = make_variant("GONE", "999.00")
    requirement = ProductRequirement(label="phone_case")

    result = filter_all([variant], requirement, stock={variant.id: out_of_stock(variant)})

    assert result.relaxable_rejections == ()


def test_filtering_an_empty_candidate_set_is_empty_rather_than_an_error() -> None:
    result = filter_all([], ProductRequirement(label="phone_case"))

    assert result.survivors == ()
    assert result.rejected == ()


# --------------------------------------------------------------------------
# The regression D§15 exists to prevent
# --------------------------------------------------------------------------


def test_a_cheaper_incompatible_product_is_never_a_candidate(
    aerocase, iphone_15_case, iphone_16
) -> None:
    """D§15's exact scenario, with the seed catalog's own products.

    The iPhone 15 case is ₹899 against the iPhone 16 case's ₹999 — cheaper on
    every price measure the ranker has. It does not appear, and it does not
    appear *because it was removed*, not because it scored lower.
    """
    requirement = ProductRequirement(
        label="phone_case",
        category_slug="phone_case",
        max_price=Decimal("1500"),
        compatibility_target=iphone_16,
    )

    result = filter_all([aerocase, iphone_15_case], requirement, compatible={aerocase.product_id})

    assert skus(result.survivors) == {aerocase.sku}
    assert HardConstraint.COMPATIBILITY in result.rejected[0].constraints


def test_the_filter_does_not_depend_on_the_weight_profile() -> None:
    """There is no profile argument here at all, and that is the design.

    ADR-005: "There is no configuration in which a cheap incompatible product
    can outrank a compatible one." The filter cannot be tuned because it takes
    no weights — the property is structural, not a matter of chosen numbers.
    """
    import inspect

    assert "profile" not in inspect.signature(apply_hard_constraints).parameters


def test_compatibility_is_resolved_before_ranking_never_inside_it() -> None:
    """`ProductRequirement.compatibility_target` is a `ResolvedTarget`.

    A phrase the model wrote cannot be typed into this field, so the ranker has
    no path to matching a device identifier itself (ADR-003).
    """
    target = ProductRequirement(
        label="phone_case",
        compatibility_target=ResolvedTarget(
            canonical_identifier="iphone_16",
            target_type="phone_model",
            display_name="iPhone 16",
            requested_text="iPhone 16",
            normalized_text="iphone_16",
        ),
    ).compatibility_target

    assert isinstance(target, ResolvedTarget)
    assert target.resolved is True


def test_the_filter_needs_no_database_and_no_model() -> None:
    """A structural assertion, deliberately trivial to read.

    `apply_hard_constraints` took a plain list, a plain mapping and a UUID and
    answered completely. That is what ADR-004 means by unit-testable without a
    database, and what makes the whole of this file possible.
    """
    result = apply_hard_constraints(
        [make_variant("PURE", "999.00")],
        ProductRequirement(label="phone_case"),
        merchant_id=MERCHANT_ID,
        stock=stock_for([make_variant("PURE", "999.00")]),
    )

    assert isinstance(result.survivors[0].id, uuid.UUID)
