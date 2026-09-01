"""The payment boundary (ADR-008, ADR-011, ADR-012).

**M10 puts exactly one thing here: `money.py`.** ADR-008 places the minor-unit
conversion in this package, and `orders.total_amount_minor` is written when an
order is created — so the two pure functions arrive with the Order Service. They
contain no client, no credentials and no network call.

The Razorpay client is **M11** and does not exist yet. A standing guard in
`tests/services/test_service_boundaries.py` names it specifically rather than
naming this package, so "no provider call before its decisions exist" stays
checkable while the conversion it depends on is available.

When the client does arrive, ADR-011 fixes what it may do: it is constructed only
in here, called only by `OrderService`, and refuses to build a provider order
from anything but a persisted `Order` row whose status is `ORDER_CREATED`.
"""

from app.payments.money import (
    CURRENCY_EXPONENT,
    MoneyConversionError,
    from_minor_units,
    to_minor_units,
)

__all__ = [
    "CURRENCY_EXPONENT",
    "MoneyConversionError",
    "from_minor_units",
    "to_minor_units",
]
