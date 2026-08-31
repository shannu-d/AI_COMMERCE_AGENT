"""Attribute comparison primitives.

One implementation of "does this product attribute satisfy this expectation",
shared by everything that has to ask. Three callers need it and they must never
disagree:

* `CompatibilityService` evaluates `compatibility_rules.constraints` against a
  product's own attributes (ADR-003);
* the ranking engine's **required specification** hard constraint eliminates a
  product whose attributes do not satisfy a stated requirement (ADR-005);
* the ranking engine's **preference** scorer counts how many stated preferences
  a product satisfies (ADR-004).

It lives at the application root for the same reason `app.canonical` does: more
than one milestone needs it, and a second implementation would eventually
disagree with the first.

There are exactly three predicate forms, and nothing else:

* ``minimum_<attr>`` — the product's ``<attr>`` must be >= the value;
* ``maximum_<attr>`` — must be <= the value;
* anything else — the attribute must equal the value.

**A missing attribute always fails.** That direction is deliberate everywhere it
is used: an expectation the catalog cannot evidence has not been shown to hold,
and neither compatibility nor a stated requirement is ever relaxed to obtain a
result.
"""

from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal, InvalidOperation
from typing import Any

__all__ = [
    "as_decimal",
    "attributes_satisfy",
    "count_satisfied",
    "numeric_at_least",
    "numeric_at_most",
    "predicate_satisfied",
    "values_equal",
]


def as_decimal(value: Any) -> Decimal | None:
    """Coerce to `Decimal`, or `None` when the value is not a number.

    Booleans are excluded on purpose: `True >= 20` is a Python accident, not a
    comparison a catalog ever means. Numeric strings are accepted because JSONB
    attributes are authored by hand and `"30"` is a plausible way to write 30.
    """
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int | float | Decimal | str):
        try:
            return Decimal(str(value))
        except (InvalidOperation, ValueError):
            return None
    return None


def numeric_at_least(actual: Any, expected: Any) -> bool:
    left, right = as_decimal(actual), as_decimal(expected)
    return left is not None and right is not None and left >= right


def numeric_at_most(actual: Any, expected: Any) -> bool:
    left, right = as_decimal(actual), as_decimal(expected)
    return left is not None and right is not None and left <= right


def values_equal(actual: Any, expected: Any) -> bool:
    """Equality as a catalog means it.

    Strings compare case-insensitively, because `"USB_C"` and `"usb_c"` are the
    same port. Booleans compare by identity, because `1 == True` is true in
    Python and is never what a product attribute meant.
    """
    if actual is None:
        return False
    if isinstance(actual, bool) or isinstance(expected, bool):
        return actual is expected
    if isinstance(actual, str) and isinstance(expected, str):
        return actual.casefold() == expected.casefold()
    return bool(actual == expected)


def predicate_satisfied(attributes: Mapping[str, Any], key: str, expected: Any) -> bool:
    """Evaluate one ``key: expected`` predicate against `attributes`."""
    if key.startswith("minimum_"):
        return numeric_at_least(attributes.get(key.removeprefix("minimum_")), expected)
    if key.startswith("maximum_"):
        return numeric_at_most(attributes.get(key.removeprefix("maximum_")), expected)
    return values_equal(attributes.get(key), expected)


def attributes_satisfy(attributes: Mapping[str, Any], predicates: Mapping[str, Any]) -> bool:
    """Whether `attributes` satisfies **every** predicate. Vacuously true when empty."""
    return all(predicate_satisfied(attributes, key, value) for key, value in predicates.items())


def count_satisfied(attributes: Mapping[str, Any], predicates: Mapping[str, Any]) -> int:
    """How many predicates `attributes` satisfies.

    The preference scorer needs the count rather than the conjunction: a product
    matching one of two stated preferences is worse than one matching both, and
    better than one matching neither (R§7).
    """
    return sum(
        1 for key, value in predicates.items() if predicate_satisfied(attributes, key, value)
    )
