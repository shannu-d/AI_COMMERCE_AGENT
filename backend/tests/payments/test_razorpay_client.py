"""The Razorpay client (M11; ADR-011, P§21, RZP-01, RZP-03).

Every test here runs with no credentials and no network, against the two-method
`RazorpayApi` protocol. That is the same seam ADR-015 draws for the model, and it
matters more than usual: this repository has no Razorpay test key, so M11's live
exit condition — *a policy PASS produces a real test-mode order* — is recorded as
unperformed rather than faked. What these tests do cover is everything the
application does with a provider's response, which is the half that can be wrong
in ways a live call would not reveal.

The properties worth asserting are mostly about the *outgoing* request. The
number sent to a provider must be the one the Policy Engine validated and the
database stored, and the only way to check that is to look at what was sent.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest

from app.domain.commerce import OrderStatus
from app.payments import RazorpayClient, RazorpayError, razorpay_order_payload
from tests.fixtures.razorpay import FakeRazorpayApi, order_response


class FakeOrder:
    """The fields the client reads. Not an ORM row: the client must work from a
    persisted order's *values*, and a fake proves it needs nothing else."""

    def __init__(self, **overrides):
        self.id = overrides.pop("id", uuid.UUID(int=42))
        self.status = overrides.pop("status", OrderStatus.ORDER_CREATED.value)
        self.total_amount = overrides.pop("total_amount", Decimal("1798.00"))
        self.total_amount_minor = overrides.pop("total_amount_minor", 179800)
        self.currency = overrides.pop("currency", "INR")
        self.razorpay_order_id = overrides.pop("razorpay_order_id", None)
        for key, value in overrides.items():
            setattr(self, key, value)


def client(*responses, key_id="rzp_test_public", merchant_name="CircuitCraft"):
    api = FakeRazorpayApi(*responses)
    return RazorpayClient(api, key_id=key_id, merchant_name=merchant_name), api


# --------------------------------------------------------------------------
# What is sent
# --------------------------------------------------------------------------


def test_the_amount_sent_is_the_stored_integer():
    """ADR-008, ADR-011. Read from the row, never recomputed.

    The conversion happened once at order creation, so what was recorded and
    what is charged are the same integer by construction rather than by two
    calls happening to agree.
    """
    order = FakeOrder(total_amount_minor=179800)
    rzp, api = client(order_response(amount=179800))

    rzp.create_order(order)

    assert api.last_payload["amount"] == 179800
    assert api.last_payload["currency"] == "INR"


def test_the_receipt_is_the_internal_order_id():
    """What makes a provider order traceable back to a local record."""
    order = FakeOrder()
    rzp, api = client(order_response(amount=179800))

    rzp.create_order(order)

    assert api.last_payload["receipt"] == str(order.id)
    assert api.last_payload["notes"]["internal_order_id"] == str(order.id)


def test_create_order_takes_an_order_not_an_amount():
    """ADR-011's "nothing from the client is authoritative", at the last step.

    A signature accepting an amount would be a signature through which some
    future caller could name a figure the Policy Engine never saw.
    """
    import inspect

    parameters = set(inspect.signature(RazorpayClient.create_order).parameters)

    assert parameters == {"self", "order"}


def test_the_payload_carries_no_secret():
    order = FakeOrder()

    payload = razorpay_order_payload(order)

    assert "key" not in payload
    assert "secret" not in str(payload).lower()


# --------------------------------------------------------------------------
# What the client refuses
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "status_value",
    ["RAZORPAY_ORDER_CREATED", "PAYMENT_CONFIRMED", "CANCELLED", "ORDER_FAILED"],
)
def test_only_an_order_awaiting_a_provider_may_be_sent(status_value):
    """ADR-011: the client refuses anything but a persisted `ORDER_CREATED` row."""
    order = FakeOrder(status=status_value)
    rzp, api = client(order_response(amount=179800))

    with pytest.raises(RazorpayError):
        rzp.create_order(order)

    assert api.call_count == 0


def test_an_order_that_already_has_a_provider_order_is_refused():
    """Otherwise a retry would create a second provider order for one purchase."""
    order = FakeOrder(razorpay_order_id="order_Existing")
    rzp, api = client(order_response(amount=179800))

    with pytest.raises(RazorpayError):
        rzp.create_order(order)

    assert api.call_count == 0


def test_a_zero_amount_is_never_sent():
    order = FakeOrder(total_amount_minor=0)
    rzp, api = client(order_response(amount=0))

    with pytest.raises(RazorpayError):
        rzp.create_order(order)

    assert api.call_count == 0


def test_a_response_with_no_order_id_is_a_failure():
    order = FakeOrder()
    rzp, _ = client({"entity": "order", "amount": 179800})

    with pytest.raises(RazorpayError, match="no order id"):
        rzp.create_order(order)


def test_an_amount_the_provider_changed_is_a_failure():
    """A mismatch means the payment page would show a figure nobody approved.

    Checked rather than trusted, because this is the last point at which the
    number can still be compared against what was authorized.
    """
    order = FakeOrder(total_amount_minor=179800)
    rzp, _ = client(order_response(amount=100))

    with pytest.raises(RazorpayError, match="not requested"):
        rzp.create_order(order)


def test_a_transport_failure_never_leaks_the_provider_message():
    """F§25. The provider's own text does not travel to a buyer."""
    order = FakeOrder()
    rzp, _ = client(RuntimeError("HTTP 500 from api.razorpay.com: invalid merchant"))

    with pytest.raises(RazorpayError) as error:
        rzp.create_order(order)

    assert "razorpay.com" not in str(error.value)
    assert "invalid merchant" not in str(error.value)
    assert error.value.transient is True


# --------------------------------------------------------------------------
# Checkout configuration (P§21, RZP-03)
# --------------------------------------------------------------------------


def test_the_checkout_config_carries_what_the_frontend_needs():
    order = FakeOrder(razorpay_order_id="order_Ready")
    rzp, _ = client(key_id="rzp_test_public")

    config = rzp.checkout_config(order)

    assert config["key"] == "rzp_test_public"
    assert config["razorpay_order_id"] == "order_Ready"
    assert config["amount"] == 179800
    assert config["currency"] == "INR"
    assert config["name"] == "CircuitCraft"


def test_the_checkout_config_carries_no_secret():
    """L§45, RZP-01, RZP-03. Asserted on the values, not on the docstring.

    The client is built with a secret-shaped string in the merchant name to make
    the check adversarial: if any field ever echoed configuration wholesale, this
    would find it.
    """
    order = FakeOrder(razorpay_order_id="order_Ready")
    rzp, _ = client(key_id="rzp_test_public")

    config = rzp.checkout_config(order)

    rendered = str(config).lower()
    assert "secret" not in rendered
    assert "webhook" not in rendered
    assert set(config) == {"key", "razorpay_order_id", "amount", "currency", "name", "receipt"}


def test_an_order_with_no_provider_order_cannot_be_checked_out():
    order = FakeOrder(razorpay_order_id=None)
    rzp, _ = client()

    with pytest.raises(RazorpayError):
        rzp.checkout_config(order)


# --------------------------------------------------------------------------
# The SDK seam
# --------------------------------------------------------------------------


def test_only_the_sdk_module_imports_the_razorpay_package():
    """ADR-011, and the same rule ADR-015 holds for the model SDK.

    A second importer would be a second path to the provider and a second place
    a credential could be read.
    """
    import ast

    from app.config import BACKEND_DIR

    importers = []
    for path in sorted((BACKEND_DIR / "app").rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            names = (
                [alias.name for alias in node.names]
                if isinstance(node, ast.Import)
                else [node.module or ""]
                if isinstance(node, ast.ImportFrom)
                else []
            )
            if any(name.split(".")[0] == "razorpay" for name in names):
                importers.append(path.relative_to(BACKEND_DIR).as_posix())

    assert importers == ["app/payments/sdk.py"]


def test_building_the_api_without_credentials_names_what_is_missing():
    """A misconfigured deployment should fail with something an operator can act
    on, not an authentication error from a vendor SDK."""
    from app.payments.sdk import build_api

    with pytest.raises(RazorpayError, match="RAZORPAY_KEY_ID"):
        build_api(None, None)
    with pytest.raises(RazorpayError, match="RAZORPAY_KEY_SECRET"):
        build_api("rzp_test_x", None)


def test_the_client_accepts_anything_shaped_like_the_protocol():
    """What makes every test in this file runnable with no credentials.

    The client is constructed here with a bare object that has the two methods
    and no relationship to the SDK at all. If `RazorpayClient` ever depended on
    a concrete type rather than on the shape, this would stop working - which is
    a stronger statement than grepping its source for a package name.
    """

    class Minimal:
        def create_order(self, payload):
            return order_response(amount=payload["amount"], order_id="order_Minimal")

        def fetch_order(self, razorpay_order_id):
            return {"id": razorpay_order_id, "status": "created"}

    rzp = RazorpayClient(Minimal(), key_id="rzp_test_public", merchant_name="CircuitCraft")

    assert rzp.create_order(FakeOrder()) == "order_Minimal"
    assert rzp.fetch_order("order_Minimal")["id"] == "order_Minimal"


def test_the_protocol_is_the_whole_provider_surface():
    """Two methods. `create` and `fetch` are the complete list of things that
    can happen to a payment provider from this application - no capture, no
    refund, and no way to ask it whether a payment succeeded, because that
    question is answered by a verified webhook and nowhere else (ADR-012).
    """
    from app.payments import RazorpayApi

    methods = {name for name in dir(RazorpayApi) if not name.startswith("_")}

    assert methods == {"create_order", "fetch_order"}
