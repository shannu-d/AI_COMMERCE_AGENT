"""Attribute comparison primitives.

`app.attributes` is the single implementation of "does this product attribute
satisfy this expectation", shared by three callers that must never disagree:
compatibility rules (ADR-003), the ranking engine's required-specification
constraint (ADR-005), and its preference scorer (ADR-004). "At least 20W" has to
mean one thing wherever it is written.

These run without a database, which matters: the equivalent assertions for
`constraints_satisfied` live in `tests/services/test_compatibility_service.py`
and are marked `requires_db` for the module they sit in, so the predicate
semantics were previously unverifiable on a machine without PostgreSQL. They
are not any more.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.attributes import (
    as_decimal,
    attributes_satisfy,
    count_satisfied,
    numeric_at_least,
    numeric_at_most,
    predicate_satisfied,
    values_equal,
)

# --------------------------------------------------------------------------
# Numeric coercion
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (30, Decimal("30")),
        (30.5, Decimal("30.5")),
        (Decimal("20"), Decimal("20")),
        ("30", Decimal("30")),
    ],
)
def test_numbers_and_numeric_strings_coerce(value: object, expected: Decimal) -> None:
    """Numeric strings are accepted because JSONB attributes are authored by
    hand and `"30"` is a plausible way to write 30."""
    assert as_decimal(value) == expected


@pytest.mark.parametrize("value", [None, True, False, "fast", "", [], {}])
def test_non_numbers_do_not_coerce(value: object) -> None:
    assert as_decimal(value) is None


def test_booleans_are_never_numbers() -> None:
    """`True >= 20` is a Python accident, not a comparison a catalog means."""
    assert as_decimal(True) is None
    assert not numeric_at_least(True, 1)


# --------------------------------------------------------------------------
# Comparison
# --------------------------------------------------------------------------


def test_at_least_is_inclusive() -> None:
    assert numeric_at_least(20, 20)
    assert numeric_at_least(30, 20)
    assert not numeric_at_least(18, 20)


def test_at_most_is_inclusive() -> None:
    assert numeric_at_most(2, 2)
    assert not numeric_at_most(3, 2)


def test_string_equality_ignores_case() -> None:
    """`USB_C` and `usb_c` are the same port."""
    assert values_equal("USB_C", "usb_c")
    assert values_equal("usb_c", "USB_C")


def test_booleans_compare_by_identity() -> None:
    """`1 == True` is true in Python and is never what a product attribute meant."""
    assert values_equal(True, True)
    assert not values_equal(1, True)
    assert not values_equal(True, 1)
    assert not values_equal(False, True)


def test_a_missing_value_never_equals_anything() -> None:
    assert not values_equal(None, "usb_c")
    assert not values_equal(None, None)


# --------------------------------------------------------------------------
# Predicates
# --------------------------------------------------------------------------


def test_the_three_predicate_forms() -> None:
    attributes = {"wattage": 30, "length_m": 2, "port_type": "usb_c"}

    assert predicate_satisfied(attributes, "minimum_wattage", 20)
    assert predicate_satisfied(attributes, "maximum_length_m", 2)
    assert predicate_satisfied(attributes, "port_type", "usb_c")


def test_a_missing_attribute_fails_every_predicate_form() -> None:
    """The direction that fails closed, and deliberately so: an expectation the
    catalog cannot evidence has not been shown to hold. Compatibility is never
    relaxed to obtain a result, and neither is a stated requirement."""
    assert not predicate_satisfied({}, "minimum_wattage", 20)
    assert not predicate_satisfied({}, "maximum_length_m", 2)
    assert not predicate_satisfied({}, "port_type", "usb_c")


def test_a_prefix_only_strips_when_it_is_the_prefix() -> None:
    """`minimum_wattage` reads the `wattage` attribute, not `minimum_wattage`."""
    assert predicate_satisfied({"wattage": 30}, "minimum_wattage", 20)
    assert not predicate_satisfied({"minimum_wattage": 30}, "minimum_wattage", 20)


def test_all_predicates_must_hold() -> None:
    attributes = {"wattage": 30, "fast_charge": True}

    assert attributes_satisfy(attributes, {"minimum_wattage": 20, "fast_charge": True})
    assert not attributes_satisfy(attributes, {"minimum_wattage": 65, "fast_charge": True})


def test_no_predicates_is_vacuously_satisfied() -> None:
    """A compatibility rule with empty `constraints` asserts nothing extra."""
    assert attributes_satisfy({"wattage": 30}, {})


def test_counting_is_not_the_same_as_conjunction() -> None:
    """The preference scorer needs the count: a product matching one of two
    preferences is worse than one matching both and better than one matching
    neither (R§7). `attributes_satisfy` would flatten all three to False."""
    attributes = {"color": "black", "material": "TPU"}
    wanted = {"color": "black", "material": "leather"}

    assert count_satisfied(attributes, wanted) == 1
    assert not attributes_satisfy(attributes, wanted)


def test_counting_an_empty_expectation_is_zero() -> None:
    assert count_satisfied({"color": "black"}, {}) == 0


# --------------------------------------------------------------------------
# The M2 assertions, now runnable without PostgreSQL
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("attributes", "predicates", "expected"),
    [
        ({"wattage": 30}, {}, True),
        ({"wattage": 20}, {"minimum_wattage": 20}, True),
        ({"wattage": 30}, {"minimum_wattage": 20}, True),
        ({"wattage": 18}, {"minimum_wattage": 20}, False),
        ({"length_m": 2}, {"maximum_length_m": 2}, True),
        ({"length_m": 3}, {"maximum_length_m": 2}, False),
        ({"fast_charge": True}, {"fast_charge": True}, True),
        ({"fast_charge": False}, {"fast_charge": True}, False),
        ({"port_type": "usb_c"}, {"port_type": "usb_c"}, True),
        ({"port_type": "USB_C"}, {"port_type": "usb_c"}, True),
        ({}, {"minimum_wattage": 20}, False),
        ({"wattage": 30}, {"fast_charge": True}, False),
        ({"wattage": True}, {"minimum_wattage": 1}, False),
        ({"fast_charge": 1}, {"fast_charge": True}, False),
        ({"wattage": "30"}, {"minimum_wattage": 20}, True),
        ({"wattage": "fast"}, {"minimum_wattage": 20}, False),
        ({"wattage": 30, "fast_charge": True}, {"minimum_wattage": 20, "fast_charge": True}, True),
        ({"wattage": 30, "fast_charge": True}, {"minimum_wattage": 65, "fast_charge": True}, False),
    ],
)
def test_compatibility_predicate_semantics_are_unchanged(
    attributes: dict, predicates: dict, expected: bool
) -> None:
    """Every case `TestConstraintPredicates` asserts, run here without a database.

    M3 moved these predicates out of `CompatibilityService` into `app.attributes`
    so the ranker could share them. This is the evidence that the move changed
    no behaviour, and it stays as the regression guard.
    """
    from app.services.compatibility_service import constraints_satisfied

    assert attributes_satisfy(attributes, predicates) is expected
    assert constraints_satisfied(attributes, predicates) is expected
