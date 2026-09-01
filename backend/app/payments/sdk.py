"""The Razorpay SDK adapter — the only module that imports the SDK (ADR-011).

The same seam ADR-015 draws for the model, one layer down: `RazorpayClient`
depends on the two-method `RazorpayApi` protocol, and this is the single
implementation that reaches a network. Every test in `tests/payments/` runs
against a double, with no credentials and no HTTP.

That matters more than it usually would. This repository has **no Razorpay test
key** — `RAZORPAY_KEY_SECRET` is still `REPLACE_ME` — so M11's live exit
condition is recorded as unperformed rather than faked. Everything the
application does with a provider response is covered; that a real test-mode order
comes back is not.

The SDK is imported lazily, inside the constructor, so importing this module
never requires the package to be installed and the application still boots on a
machine that has never seen it.
"""

from __future__ import annotations

from typing import Any

from app.payments.razorpay_client import RazorpayError

__all__ = ["RazorpaySdkApi", "build_api"]


class RazorpaySdkApi:
    """`RazorpayApi` backed by the official SDK."""

    def __init__(self, key_id: str, key_secret: str) -> None:
        try:
            import razorpay
        except ImportError as exc:  # pragma: no cover - depends on the environment
            raise RazorpayError(
                "the razorpay package is not installed; install it to reach the provider"
            ) from exc

        self._client = razorpay.Client(auth=(key_id, key_secret))

    def create_order(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._client.order.create(data=payload)

    def fetch_order(self, razorpay_order_id: str) -> dict[str, Any]:
        return self._client.order.fetch(razorpay_order_id)


def build_api(key_id: str | None, key_secret: str | None) -> RazorpaySdkApi:
    """The live API, or a refusal that names what is missing.

    Refusing here rather than at the first call means a misconfigured deployment
    fails when an order is attempted, with a message an operator can act on,
    instead of producing an authentication error from a vendor SDK.
    """
    if not key_id or not key_secret:
        raise RazorpayError(
            "RAZORPAY_KEY_ID and RAZORPAY_KEY_SECRET must be configured to reach the provider"
        )
    return RazorpaySdkApi(key_id, key_secret)
