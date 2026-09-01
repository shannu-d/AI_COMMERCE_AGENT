"""The Razorpay client (M11; ADR-011, P§17–P§21, RZP-01, RZP-03).

The only module in this application that talks to a payment provider, and the
narrowest one that could do the job: it creates a test-mode order and reads one
back. It does not capture, refund, or interpret a payment — payment truth arrives
by verified webhook and nowhere else (ADR-012).

**It refuses to build a provider order from anything but a persisted `Order`
row.** `create_order` takes an `Order`, not an amount, and checks that the row is
in `ORDER_CREATED` with no `razorpay_order_id` yet. There is no argument through
which a caller could name a different figure, which is what makes ADR-011's
"nothing from the client is authoritative" survive the last step of the path: the
number sent to Razorpay is the one the Policy Engine validated and the database
stored.

**The seam is a protocol, exactly as ADR-015 does for the model.** `RazorpayApi`
has two methods; `RazorpayClient` depends on it rather than on the SDK. That is
what lets every test here run with no credentials and no network — which matters
more than usual, because this repository has no Razorpay test key and the live
verification of M11 is therefore recorded as unperformed rather than faked.

**Secrets never leave.** `checkout_config` returns the **public** key id, the
amount in minor units, the currency and the merchant name. `RAZORPAY_KEY_SECRET`
and `RAZORPAY_WEBHOOK_SECRET` appear in no response, reach no frontend and enter
no prompt (L§45, RZP-01, RZP-03), and a test asserts the config dict cannot carry
one.
"""

from __future__ import annotations

import logging
from typing import Any, Protocol, runtime_checkable

from app.db.models import Order
from app.domain.commerce import OrderStatus

logger = logging.getLogger(__name__)

__all__ = [
    "CheckoutConfig",
    "RazorpayApi",
    "RazorpayClient",
    "RazorpayError",
    "razorpay_order_payload",
]


class RazorpayError(Exception):
    """A provider call that did not succeed.

    Carries no provider response body: F§25 forbids rendering one to a buyer,
    and the reconciliation path needs the local order row rather than the
    provider's prose.
    """

    def __init__(self, message: str, *, transient: bool = False) -> None:
        self.transient = transient
        super().__init__(message)


@runtime_checkable
class RazorpayApi(Protocol):
    """The two calls this application makes. Nothing else is reachable.

    Deliberately not the SDK's client object. A protocol with two methods is a
    surface small enough to fake honestly, and it is what keeps `create` and
    `fetch` the complete list of things that can happen to a payment provider
    from here.
    """

    def create_order(self, payload: dict[str, Any]) -> dict[str, Any]: ...

    def fetch_order(self, razorpay_order_id: str) -> dict[str, Any]: ...


class CheckoutConfig(dict):
    """What the frontend needs to open Checkout, and nothing more (P§21)."""


def razorpay_order_payload(order: Order) -> dict[str, Any]:
    """The provider payload for one persisted order.

    `amount` is `orders.total_amount_minor` — read from the row, not recomputed.
    The conversion happened once at order creation (ADR-008), so what was
    recorded and what is charged are the same integer by construction rather
    than by two calls agreeing.

    `receipt` is the internal order id, which is what makes a provider order
    traceable back to a local record during reconciliation.
    """
    return {
        "amount": order.total_amount_minor,
        "currency": order.currency,
        "receipt": str(order.id),
        # Razorpay auto-captures when this is set; ADR-012 still treats the
        # webhook as the only payment truth, so this changes what the provider
        # does and not what this application believes.
        "payment_capture": 1,
        "notes": {"internal_order_id": str(order.id)},
    }


class RazorpayClient:
    """Creates and reads Razorpay orders. Called only by `OrderService`."""

    def __init__(self, api: RazorpayApi, *, key_id: str, merchant_name: str) -> None:
        self._api = api
        self._key_id = key_id
        self._merchant_name = merchant_name

    def create_order(self, order: Order) -> str:
        """Create the provider order for a persisted internal one.

        Returns the provider's order id. Raises rather than returning `None`:
        a failure here leaves the internal order in `ORDER_CREATED` with a null
        `razorpay_order_id`, which is a visible, retryable, auditable state
        (ADR-011) — and the caller must know to leave it that way rather than
        marking it advanced.
        """
        if order.status != OrderStatus.ORDER_CREATED.value:
            raise RazorpayError(f"an order in {order.status} is not awaiting a provider order")
        if order.razorpay_order_id is not None:
            raise RazorpayError("this order already has a provider order")
        if order.total_amount_minor <= 0:
            raise RazorpayError("an order of zero cannot be sent to a payment provider")

        try:
            response = self._api.create_order(razorpay_order_payload(order))
        except RazorpayError:
            raise
        except Exception as exc:
            # The provider's own message never travels. A retry reuses this same
            # internal order and the same idempotency key, so a network failure
            # cannot produce two provider orders (ADR-011, ADR-013).
            logger.warning("razorpay order creation failed", extra={"order_id": str(order.id)})
            raise RazorpayError(
                "the payment provider could not be reached", transient=True
            ) from exc

        provider_id = response.get("id")
        if not provider_id or not isinstance(provider_id, str):
            raise RazorpayError("the payment provider returned no order id")

        # The provider is asked for an amount and must not answer with a
        # different one. Checked rather than trusted: a mismatch here means the
        # payment page would show a figure nobody approved.
        returned = response.get("amount")
        if returned is not None and int(returned) != order.total_amount_minor:
            raise RazorpayError("the payment provider returned an amount that was not requested")

        logger.info(
            "razorpay order created",
            extra={"order_id": str(order.id), "razorpay_order_id": provider_id},
        )
        return provider_id

    def fetch_order(self, razorpay_order_id: str) -> dict[str, Any]:
        """Read a provider order back, for reconciliation.

        Used by the recovery path when an internal order has no provider id and
        it is unclear whether the earlier call reached them. It is never used to
        decide that a payment succeeded — only a verified webhook does that.
        """
        try:
            return self._api.fetch_order(razorpay_order_id)
        except Exception as exc:
            raise RazorpayError(
                "the payment provider could not be reached", transient=True
            ) from exc

    def checkout_config(self, order: Order) -> CheckoutConfig:
        """What the frontend needs to open Checkout (P§21, RZP-03).

        The **public** key id, the amount in minor units, the currency, the
        merchant display name and the provider order id. No secret appears here,
        and a standing test asserts that by checking the values rather than
        trusting this docstring.

        The frontend's success callback is not payment truth (P§28, ADR-012).
        """
        if order.razorpay_order_id is None:
            raise RazorpayError("this order has no provider order to check out")

        return CheckoutConfig(
            key=self._key_id,
            razorpay_order_id=order.razorpay_order_id,
            amount=order.total_amount_minor,
            currency=order.currency,
            name=self._merchant_name,
            # The internal id, so a support conversation about a payment can
            # start from something this application recognises.
            receipt=str(order.id),
        )
