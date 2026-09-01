"""The payment boundary (ADR-008, ADR-011, ADR-012).

`money.py` (M10) holds ADR-008's minor-unit conversion, because
`orders.total_amount_minor` is written when an order is created.
`razorpay_client.py` and `sdk.py` (M11) are the provider boundary.

ADR-011 fixes what the client may do, and the shape enforces it: it is
constructed only here, called only by `OrderService`, and `create_order` takes a
persisted `Order` row rather than an amount - so the figure sent to a provider
is the one the Policy Engine validated and the database stored. There is no
argument through which a caller could name a different one.

`sdk.py` is the only module that imports the Razorpay package, which is the same
seam ADR-015 draws for the model. Every test runs against the `RazorpayApi`
protocol with no credentials and no HTTP.

**Secrets never leave the backend.** `checkout_config` returns the *public* key
id; `RAZORPAY_KEY_SECRET` and `RAZORPAY_WEBHOOK_SECRET` appear in no response,
reach no frontend and enter no prompt (L§45, RZP-01, RZP-03).
"""

from app.payments.money import (
    CURRENCY_EXPONENT,
    MoneyConversionError,
    from_minor_units,
    to_minor_units,
)
from app.payments.razorpay_client import (
    CheckoutConfig,
    RazorpayApi,
    RazorpayClient,
    RazorpayError,
    razorpay_order_payload,
)

__all__ = [
    "CURRENCY_EXPONENT",
    "CheckoutConfig",
    "MoneyConversionError",
    "RazorpayApi",
    "RazorpayClient",
    "RazorpayError",
    "from_minor_units",
    "razorpay_order_payload",
    "to_minor_units",
]
