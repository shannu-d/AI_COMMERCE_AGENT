"""Decimal money to integer minor units, and back (ADR-008).

Two functions, in one module, and they are the **only** place in the application
where an integer minor-unit amount is produced or consumed:

    Decimal("1798.00")  --to_minor_units()-->  179800  -->  Razorpay
    Decimal("1798.00")  <--from_minor_units()--  179800  <--  a verified webhook

Everywhere else money is `Decimal` and `NUMERIC(12,2)`. Razorpay's API transacts
in paise; having two money representations loose in one codebase is how a paise
value reaches a rupee field, so the conversion happens at one boundary and is
written down once.

**`to_minor_units` raises rather than rounds** on an amount with more precision
than the currency has. A price of `Decimal("999.999")` is a bug upstream - the
schema is `NUMERIC(12,2)` and nothing should have produced it - and silently
rounding at the payment boundary would turn a data defect into a charge nobody
can explain afterwards.

This module lives in `app/payments/` because ADR-008 places it there, and it
arrives with M10 rather than M11 because `orders.total_amount_minor` is written
when the order is created. It contains no client, no credentials and no network
call; the Razorpay client is M11 and a standing guard still forbids it.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

__all__ = ["CURRENCY_EXPONENT", "MoneyConversionError", "from_minor_units", "to_minor_units"]

#: Digits after the decimal point, per ISO-4217. INR and most currencies use 2;
#: JPY uses 0 and KWD uses 3, which is why this is a table rather than `* 100`.
CURRENCY_EXPONENT: dict[str, int] = {
    "INR": 2,
    "USD": 2,
    "EUR": 2,
    "GBP": 2,
    "JPY": 0,
    "KWD": 3,
}


class MoneyConversionError(ValueError):
    """An amount that cannot be converted without losing or inventing value."""


def _exponent(currency: str) -> int:
    code = currency.upper()
    if code not in CURRENCY_EXPONENT:
        raise MoneyConversionError(f"no minor-unit exponent is known for {currency!r}")
    return CURRENCY_EXPONENT[code]


def to_minor_units(amount: Decimal, currency: str) -> int:
    """The integer a payment provider is sent.

    Quantizes to the currency's exponent with `ROUND_HALF_UP` and then **raises**
    if that changed the value. The quantize is what makes `Decimal("1798.0")` and
    `Decimal("1798.00")` produce the same integer; the check is what stops
    `Decimal("999.999")` quietly becoming ₹1,000.00.
    """
    if not isinstance(amount, Decimal):
        raise MoneyConversionError(f"money must be Decimal, not {type(amount).__name__} (ADR-008)")
    if amount < 0:
        raise MoneyConversionError("a negative amount cannot be charged")

    exponent = _exponent(currency)
    try:
        quantized = amount.quantize(Decimal(1).scaleb(-exponent), rounding=ROUND_HALF_UP)
    except InvalidOperation as exc:  # an amount too large for the context
        raise MoneyConversionError(f"{amount} cannot be represented in {currency}") from exc

    if quantized != amount:
        raise MoneyConversionError(
            f"{amount} has more precision than {currency} has minor units; "
            "this is a defect upstream, not something to round here"
        )
    return int(quantized.scaleb(exponent))


def from_minor_units(minor: int, currency: str) -> Decimal:
    """The `Decimal` a provider's integer means.

    `bool` is refused explicitly: it is an `int` in Python, and `True` arriving
    where an amount was expected should fail loudly rather than become ₹0.01.
    """
    if isinstance(minor, bool) or not isinstance(minor, int):
        raise MoneyConversionError(f"minor units must be int, not {type(minor).__name__} (ADR-008)")
    if minor < 0:
        raise MoneyConversionError("a negative amount cannot be charged")

    return (Decimal(minor).scaleb(-_exponent(currency))).quantize(
        Decimal(1).scaleb(-_exponent(currency))
    )
