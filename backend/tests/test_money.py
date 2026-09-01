"""Decimal to integer minor units, and back (ADR-008).

ADR-008 names these as M11 tests; they arrive with M10 because
`orders.total_amount_minor` is written when the order is created. Nothing here
needs a database — the conversion is two pure functions, which is the point of
having exactly one module that does it.

The property that matters is the round trip. Everything else is about refusing
to guess: an amount with more precision than the currency has is a defect
upstream, and rounding it here would turn a data problem into a charge nobody can
explain afterwards.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.payments.money import (
    CURRENCY_EXPONENT,
    MoneyConversionError,
    from_minor_units,
    to_minor_units,
)


@pytest.mark.parametrize(
    "amount",
    ["0.00", "0.01", "0.05", "1.00", "999.99", "1798.00", "1500.10", "99999999.99"],
)
def test_the_round_trip_is_exact(amount: str) -> None:
    """ADR-008's named test, across its named range."""
    value = Decimal(amount)

    assert from_minor_units(to_minor_units(value, "INR"), "INR") == value


def test_the_worked_example() -> None:
    """₹1,798.00 is 179800 paise."""
    assert to_minor_units(Decimal("1798.00"), "INR") == 179800
    assert from_minor_units(179800, "INR") == Decimal("1798.00")


def test_scale_does_not_change_the_integer() -> None:
    """`Decimal("1798")` and `Decimal("1798.00")` are the same amount."""
    assert to_minor_units(Decimal("1798"), "INR") == to_minor_units(Decimal("1798.00"), "INR")


def test_more_precision_than_the_currency_has_raises() -> None:
    """A defect upstream, not something to silently round at the payment
    boundary. The schema is NUMERIC(12,2); nothing should have produced this."""
    with pytest.raises(MoneyConversionError, match="more precision"):
        to_minor_units(Decimal("999.999"), "INR")


def test_a_float_is_refused() -> None:
    """The rule the whole codebase rests on: money is never a float."""
    with pytest.raises(MoneyConversionError, match="Decimal"):
        to_minor_units(1798.00, "INR")  # type: ignore[arg-type]


def test_a_bool_is_not_an_amount() -> None:
    """`True` is an `int` in Python, and would otherwise become ₹0.01."""
    with pytest.raises(MoneyConversionError, match="int"):
        from_minor_units(True, "INR")  # type: ignore[arg-type]


def test_a_negative_amount_cannot_be_charged() -> None:
    with pytest.raises(MoneyConversionError):
        to_minor_units(Decimal("-1.00"), "INR")
    with pytest.raises(MoneyConversionError):
        from_minor_units(-1, "INR")


def test_an_unknown_currency_raises_rather_than_assuming_two_places() -> None:
    """Assuming ×100 is how a JPY amount becomes a hundred times too large."""
    with pytest.raises(MoneyConversionError, match="exponent"):
        to_minor_units(Decimal("100.00"), "XYZ")


def test_a_zero_exponent_currency_does_not_multiply() -> None:
    """JPY has no minor unit; ¥100 is 100, not 10000."""
    assert to_minor_units(Decimal("100"), "JPY") == 100
    assert from_minor_units(100, "JPY") == Decimal("100")


def test_a_three_exponent_currency_multiplies_by_a_thousand() -> None:
    """KWD is why this is a table rather than `* 100`."""
    assert to_minor_units(Decimal("1.234"), "KWD") == 1234


@pytest.mark.parametrize("currency", sorted(CURRENCY_EXPONENT))
def test_every_known_currency_round_trips_zero(currency: str) -> None:
    assert from_minor_units(to_minor_units(Decimal("0"), currency), currency) == Decimal("0")


def test_the_currency_code_is_case_insensitive() -> None:
    assert to_minor_units(Decimal("1.00"), "inr") == 100
