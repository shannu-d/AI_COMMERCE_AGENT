"""Razorpay doubles (M11; ADR-011).

ADR-011 reserves `backend/tests/fixtures/` for these and forbids them in
application code, which is the same rule ADR-015 applies to the model: a double
that lived beside the client would eventually be importable from it.

`FakeRazorpayApi` implements the two-method `RazorpayApi` protocol, replays a
script, and records every payload it was sent. Recording matters as much as
replaying — several properties M11 must have are properties of the *outgoing*
request (that the amount is the stored integer, that the receipt is the internal
order id) and can only be asserted by looking at what was sent.

The captured responses below are shaped like Razorpay's, from its published
order API. They are **not** recorded from a live call: this repository has no
Razorpay test key, and a hand-written fixture that claimed to be a recording
would be the fiction ADR-015 rejects for the model.
"""

from __future__ import annotations

from typing import Any

__all__ = ["FakeRazorpayApi", "order_response"]


def order_response(
    *, amount: int, currency: str = "INR", order_id: str = "order_TestModeXYZ", **extra: Any
) -> dict[str, Any]:
    """A provider order response, in Razorpay's documented shape."""
    return {
        "id": order_id,
        "entity": "order",
        "amount": amount,
        "amount_paid": 0,
        "amount_due": amount,
        "currency": currency,
        "receipt": extra.pop("receipt", "rcpt"),
        "status": "created",
        "attempts": 0,
        "created_at": 1_756_700_000,
        **extra,
    }


class FakeRazorpayApi:
    """A `RazorpayApi` that replays a script and remembers every call.

    Each queued item is a response to return or an exception to raise, so a test
    can script "fails, then succeeds" without patching anything. Running past
    the end of the script is a test bug rather than a default response, and says
    so.
    """

    def __init__(self, *responses: dict[str, Any] | Exception) -> None:
        self.queued: list[dict[str, Any] | Exception] = list(responses)
        self.created: list[dict[str, Any]] = []
        self.fetched: list[str] = []

    def create_order(self, payload: dict[str, Any]) -> dict[str, Any]:
        self.created.append(payload)
        return self._next("create_order")

    def fetch_order(self, razorpay_order_id: str) -> dict[str, Any]:
        self.fetched.append(razorpay_order_id)
        return self._next("fetch_order")

    def _next(self, call: str) -> dict[str, Any]:
        if not self.queued:
            raise AssertionError(f"{call} was called more times than the script has responses")
        item = self.queued.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    # -- convenience for assertions ----------------------------------------

    @property
    def call_count(self) -> int:
        return len(self.created) + len(self.fetched)

    @property
    def last_payload(self) -> dict[str, Any]:
        assert self.created, "no order was created"
        return self.created[-1]
