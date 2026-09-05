"""Driving one evaluation case through the real system.

Three runners, because the brief asks about three surfaces and they have
genuinely different shapes:

* `run_agent_case` - the conversational agent. Real `AgentRuntime`, real
  registry, real executor, real services, real ranking engine, real database.
  Only the model is scripted, at the `LLMClient` seam ADR-015 draws.
* `run_mcp_case` - the MCP surface an external AI buyer sees, driven through
  `call_tool` exactly as a client would.
* `run_commerce_case` - the money path: cart, approval, the Policy Engine,
  order creation, idempotency, and the two drift scenarios.

**Nothing here is faked except the model and the payment provider.** Those two
are the seams ADR-015 and ADR-011 already draw for the rest of the suite; every
other component under a case is the one that ships. A runner that stubbed the
ranking engine or the Policy Engine would be evaluating the evaluator.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from decimal import Decimal
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.agent.context import AgentContext
from app.agent.registry import build_registry
from app.agent.runtime import AgentRuntime
from app.config import get_settings
from app.services.approval_service import ApprovalError, ApprovalService
from app.services.cart_service import CartError, CartService
from app.services.catalog_service import CatalogService
from app.services.order_service import OrderError, OrderService
from app.services.session_service import SessionService
from tests.evals.observation import Observation
from tests.evals.scripted_model import ScriptedModel

__all__ = ["run_case"]


def run_case(case: dict[str, Any], db: Session, merchant_id: uuid.UUID) -> Observation:
    """Dispatch on the case's surface.

    One entry point, so the runner CLI and the pytest module cannot drift apart.
    """
    mode = case.get("mode", "agent")
    runners = {
        "agent": run_agent_case,
        "mcp": run_mcp_case,
        "commerce": run_commerce_case,
    }
    runner = runners.get(mode)
    if runner is None:
        return Observation(case_id=case["id"], mode=mode, crashed=f"unknown mode {mode!r}")
    try:
        return runner(case, db, merchant_id)
    except Exception as exc:  # a runner fault must be visible, never a pass
        return Observation(case_id=case["id"], mode=mode, crashed=f"{type(exc).__name__}: {exc}")


# --------------------------------------------------------------------------
# Shared observations
# --------------------------------------------------------------------------


def _order_count(db: Session, merchant_id: uuid.UUID) -> int:
    return int(
        db.execute(
            text("SELECT count(*) FROM orders WHERE merchant_id = :m"), {"m": merchant_id}
        ).scalar_one()
    )


def _approval_statuses(db: Session, session_id: uuid.UUID) -> list[str]:
    return list(
        db.execute(
            text(
                "SELECT a.status FROM approvals a JOIN carts c ON c.id = a.cart_id "
                "WHERE c.session_id = :s ORDER BY a.created_at"
            ),
            {"s": session_id},
        )
        .scalars()
        .all()
    )


class _EchoingRazorpayApi:
    """A `RazorpayApi` that echoes back the amount it was asked for.

    `tests/fixtures/razorpay.py` replays a fixed script, which is right for the
    payment tests that assert on one known order. It is wrong here: the suite
    creates orders of many different totals, and `RazorpayClient` checks that
    the provider did not answer with an amount other than the one requested -
    correctly, because a mismatch means the payment page would show a figure
    nobody approved. Against a fixed script that guard fires on every order but
    one, for a reason that has nothing to do with the system under test.

    So this echoes, and records. The client's own guards still run above it.
    """

    def __init__(self) -> None:
        self.created: list[dict[str, Any]] = []
        self.fetched: list[str] = []

    def create_order(self, payload: dict[str, Any]) -> dict[str, Any]:
        from tests.fixtures.razorpay import order_response

        self.created.append(payload)
        return order_response(
            amount=int(payload["amount"]),
            currency=str(payload.get("currency", "INR")),
            order_id=f"order_Eval{len(self.created):04d}",
            receipt=payload.get("receipt", "rcpt"),
        )

    def fetch_order(self, razorpay_order_id: str) -> dict[str, Any]:
        from tests.fixtures.razorpay import order_response

        self.fetched.append(razorpay_order_id)
        return order_response(amount=0, order_id=razorpay_order_id)


class RecordingProvider:
    """The real `RazorpayClient` over a recording double, at ADR-011's seam.

    Not a stub of the client: the client's own guards - that the order is in
    `ORDER_CREATED`, that it has no provider order already, that the amount is
    positive, that the provider echoed what was requested - are part of what a
    payment-safety case is checking, so the double goes underneath them, at the
    `RazorpayApi` protocol `tests/fixtures` already defines for exactly this.

    The `calls` list is what `no_payment_attempted` and `no_provider_order`
    read. Recording the attempt matters more than refusing it: a case must be
    able to distinguish "the system declined to charge" from "the system tried
    and the provider happened to be unreachable", and an unconfigured key makes
    those two look identical.
    """

    def __init__(self, merchant_name: str) -> None:
        from app.payments.razorpay_client import RazorpayClient

        self.api = _EchoingRazorpayApi()
        self.client = RazorpayClient(
            self.api, key_id="rzp_test_evaluation", merchant_name=merchant_name
        )

    @property
    def calls(self) -> list[str]:
        return [f"create_order({payload.get('receipt')})" for payload in self.api.created]


# --------------------------------------------------------------------------
# The agent
# --------------------------------------------------------------------------


def run_agent_case(case: dict[str, Any], db: Session, merchant_id: uuid.UUID) -> Observation:
    """One conversation, one to many turns, through the real runtime.

    A multi-turn case reuses one session id and gives each turn its own scripted
    model with no memory of the last, so what is evaluated is what the
    *application* carried across turns - the session history and the cart -
    rather than anything the model remembered for itself.

    There is no provider double here because the agent has no path to a
    provider: `create_order` is not a tool at any milestone. The safety claim on
    this surface is `no_order_created` and `no_approval_granted`, not a call
    that did not happen.
    """
    settings = get_settings()
    context = AgentContext.from_session(db, merchant_id)
    session_id = context.sessions.create(merchant_id).id

    obs = Observation(case_id=case["id"], mode="agent")
    obs.extras["orders_before"] = _order_count(db, merchant_id)

    turns = case.get("turns") or [{"user": case.get("prompt", ""), "model_plan": []}]

    for index, turn in enumerate(turns):
        model = ScriptedModel(
            turn.get("model_plan", []),
            fallback=turn.get("fallback", "Here is what I found."),
        )
        runtime = AgentRuntime(
            model,
            build_registry(),
            context,
            max_tool_calls_per_turn=settings.max_tool_calls_per_turn,
            trace_enabled=True,
            top_k=settings.ranking_top_k,
        )
        result = runtime.run_turn(session_id, turn.get("user", ""))

        # The last turn is the one graded; earlier turns are setup that still
        # had to happen through the real system.
        obs.message = result.message
        obs.recommendations = list(result.recommendations)
        obs.cart = result.cart
        obs.error = (
            None
            if result.error is None
            else {"code": result.error.code.value, "message": result.error.message}
        )
        for recorded in (result.trace or {}).get("tool_calls", []):
            obs.tool_calls.append({**recorded, "turn": index})
        obs.offered_tools = tuple(sorted(set(obs.offered_tools) | set(model.offered_tool_names)))
        obs.extras.setdefault("states", []).append(result.state.value)

    obs.turn_count = len(turns)
    obs.extras["orders_after"] = _order_count(db, merchant_id)
    obs.extras["approval_statuses"] = _approval_statuses(db, session_id)
    obs.extras["session_id"] = str(session_id)
    if obs.cart:
        obs.extras["quotable_totals"] = [obs.cart.get("total"), obs.cart.get("subtotal")]
    return obs


# --------------------------------------------------------------------------
# MCP
# --------------------------------------------------------------------------


def _mcp_call(server: Any, name: str, args: dict[str, Any]) -> dict[str, Any]:
    async def run() -> dict[str, Any]:
        result = await server.call_tool(name, args)
        content = result[0] if isinstance(result, tuple) else result
        for part in content:
            if hasattr(part, "text"):
                return json.loads(part.text)
        raise AssertionError(f"no text content from {name}")

    try:
        return asyncio.run(run())
    except Exception as exc:  # FastMCP raises on a tool error; that is a result
        return {"status": "error", "raised": f"{type(exc).__name__}: {exc}"}


def run_mcp_case(case: dict[str, Any], db: Session, merchant_id: uuid.UUID) -> Observation:
    """The MCP surface, driven the way an external buyer's agent drives it.

    `steps` is a small script. Each step names a tool and its arguments and may
    bind values out of a previous step's result, because an external agent's
    second call is always shaped by its first. A step may also be a `drift`,
    which moves the catalogue between two calls - the only way to test a stale
    quote, since the quote was honest at the moment it was given.
    """
    import app.mcp.server as mcp_server

    server = case["_server"]
    provider = RecordingProvider(get_settings().default_merchant_name)
    obs = Observation(case_id=case["id"], mode="mcp")
    obs.extras["orders_before"] = _order_count(db, merchant_id)

    # The provider is replaced rather than merely left unconfigured.
    # Unconfigured makes `authorize_and_pay` fail on the way to Razorpay, which
    # in a payload looks the same as refusing to go there; this records the
    # attempt, so a case asserting no payment was tried asserts something.
    original = mcp_server._razorpay_client
    mcp_server._razorpay_client = lambda settings: provider.client  # type: ignore[assignment]

    last: dict[str, Any] = {}
    quote: dict[str, Any] | None = None
    try:
        for step in case["steps"]:
            if "drift" in step:
                _apply_drift(db, merchant_id, step["drift"])
                db.commit()
                continue
            args = dict(step.get("arguments", {}))
            for field, source in (step.get("bind") or {}).items():
                if source == "quote_reference" and quote:
                    args[field] = quote["quote_reference"]
                elif source == "quote_total" and quote:
                    args[field] = quote["total"]
                elif source == "order_id":
                    args[field] = last.get("order_id", "")
            last = _mcp_call(server, step["tool"], args)
            if step["tool"] == "create_quote" and "total" in last:
                quote = last
            obs.tool_calls.append(
                {"tool": step["tool"], "arguments": args, "result": _as_tool_result(last)}
            )
    finally:
        mcp_server._razorpay_client = original  # type: ignore[assignment]

    obs.extras["provider_calls"] = provider.calls
    obs.extras["mcp_result"] = last
    obs.extras["quote"] = quote
    obs.extras["orders_after"] = _order_count(db, merchant_id)
    obs.extras["payload_rows"] = _mcp_rows(obs)
    obs.extras["money_bearing"] = [last] if isinstance(last, dict) else []
    return obs


def _as_tool_result(payload: dict[str, Any]) -> dict[str, Any]:
    """An MCP payload in the shape the shared checks read.

    The MCP tools answer in their own vocabulary - `{"status": "rejected"}`, or
    an `error` object - so it is normalised here rather than in every check.
    """
    if payload.get("status") in {"rejected", "error"} or "error" in payload:
        error = payload.get("error", {})
        code = payload.get("code") or error.get("code") or "REJECTED"
        return {"success": False, "error": {"code": code, "message": payload.get("message", "")}}
    return {"success": True, "result": payload}


def _mcp_rows(obs: Observation) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for call in obs.tool_calls:
        payload = call.get("result", {})
        if not payload.get("success"):
            continue
        body = payload.get("result", {})
        for key in ("items", "results", "variants", "lines", "alternatives", "candidates"):
            rows.extend(body.get(key) or [])
    return [row for row in rows if isinstance(row, dict)]


# --------------------------------------------------------------------------
# The money path
# --------------------------------------------------------------------------


def run_commerce_case(case: dict[str, Any], db: Session, merchant_id: uuid.UUID) -> Observation:
    """Cart, approval, drift, the Policy Engine and order creation.

    Every case here has the same shape, and it is the shape of the whole
    architecture: build a cart from real SKUs, optionally approve it, optionally
    move the catalogue underneath the approval, then try to create an order and
    record exactly what the system did about it.
    """
    settings = get_settings()
    catalog = CatalogService(db)
    carts = CartService(db)
    approvals = ApprovalService(db, ttl_seconds=settings.approval_ttl_seconds)
    sessions = SessionService(db)

    obs = Observation(case_id=case["id"], mode="commerce")
    obs.extras["orders_before"] = _order_count(db, merchant_id)
    obs.extras["provider_calls"] = []

    session_id = sessions.create(merchant_id).id
    cart = None
    for line in case["cart"]:
        variant = catalog.get_variant_by_sku(merchant_id, line["sku"])
        if variant is None:
            obs.crashed = f"the case names SKU {line['sku']!r}, which is not in the catalogue"
            return obs
        try:
            cart = carts.add_item(merchant_id, session_id, variant.id, line.get("quantity", 1))
        except CartError as error:
            obs.extras["cart_error"] = {"code": error.code, "message": error.message}
            obs.extras["orders_after"] = obs.extras["orders_before"]
            return obs
    assert cart is not None
    obs.cart = _cart_payload(cart)
    obs.extras["cart"] = obs.cart

    # 1. Optional approval, at the total as it stands now.
    approval_error: dict[str, Any] | None = None
    if case.get("approve", False):
        approvals.request(session_id, cart)
        try:
            approvals.approve(
                session_id,
                cart,
                cart_version=cart.version,
                expected_total=Decimal(str(case.get("approved_total", cart.total))),
            )
        except ApprovalError as error:
            approval_error = {
                "code": error.failure.value,
                "message": error.message,
                "details": error.details,
            }
    elif case.get("request_approval_only", False):
        # A PENDING approval with no confirmation behind it. Distinct from no
        # approval at all, and the case that exercises the Policy Engine's first
        # rule rather than the idempotency gate in front of it.
        approvals.request(session_id, cart)
    obs.extras["approval_error"] = approval_error

    # 2. Optional drift, applied *after* the buyer approved.
    #
    #    The cart is deliberately not refreshed here. Refreshing would re-price
    #    it and bump its version, which is a different scenario; the one under
    #    test is an approval that is still nominally current while the catalogue
    #    beneath it has moved. `OrderService` re-reads live price and takes
    #    `SELECT ... FOR UPDATE` on the inventory rows inside the order
    #    transaction, which is where the drift has to be caught.
    for drift in case.get("drift", []):
        _apply_drift(db, merchant_id, drift)

    # 3. Order creation, through the service that owns the transaction. The
    #    Policy Engine's verdict is read out of *that* path rather than
    #    reassembled here: `OrderService` builds the `TransactionContext` with
    #    the inventory rows locked, and an evaluator that assembled its own
    #    would be grading its own assembly.
    if case.get("create_order", True):
        obs.extras.update(_attempt_orders(db, merchant_id, session_id, cart, approvals, case))

    obs.extras["orders_after"] = _order_count(db, merchant_id)
    obs.extras["approval_statuses"] = _approval_statuses(db, session_id)
    obs.extras["money_bearing"] = [obs.cart]
    return obs


def _cart_payload(cart: Any) -> dict[str, Any]:
    from app.agent.tools.cart import serialize_cart

    return serialize_cart(cart)


def _apply_drift(db: Session, merchant_id: uuid.UUID, drift: dict[str, Any]) -> None:
    """Move the catalogue under an approval that has already been given."""
    kind = drift["kind"]
    sku = drift["sku"]
    if kind == "price":
        db.execute(
            text("UPDATE product_variants SET price = :p WHERE sku = :s AND merchant_id = :m"),
            {"p": Decimal(str(drift["to"])), "s": sku, "m": merchant_id},
        )
    elif kind == "price_delta":
        db.execute(
            text(
                "UPDATE product_variants SET price = price + :d WHERE sku = :s AND merchant_id = :m"
            ),
            {"d": Decimal(str(drift["delta"])), "s": sku, "m": merchant_id},
        )
    elif kind == "stock":
        db.execute(
            text(
                "UPDATE inventory SET quantity = :q WHERE variant_id = "
                "(SELECT id FROM product_variants WHERE sku = :s AND merchant_id = :m)"
            ),
            {"q": int(drift["to"]), "s": sku, "m": merchant_id},
        )
    else:  # pragma: no cover - a case-file bug
        raise ValueError(f"unknown drift kind {kind!r}")
    db.flush()


def _attempt_orders(
    db: Session,
    merchant_id: uuid.UUID,
    session_id: uuid.UUID,
    cart: Any,
    approvals: ApprovalService,
    case: dict[str, Any],
) -> dict[str, Any]:
    """Try to create the order, once or twice.

    Twice when the case is about idempotency: the same key presented again must
    resolve to one logical order, and the only way to see that is to present it
    again.

    **The key is the one the approval minted, and with no approval there is no
    key.** That is not a gap in the evaluation, it is the outermost gate.
    `POST /api/orders` is reached with a key the application issued alongside an
    approval, so an order attempted without one is refused for a key that was
    never issued, before the Policy Engine is even asked. The observation
    records which of the two gates refused, and
    `order_refused_without_approval` accepts either while insisting on the thing
    that matters: no order, no provider call.
    """
    settings = get_settings()
    service = OrderService(
        db,
        spending_limit=settings.spending_limit,
        spending_limit_currency=settings.spending_limit_currency,
        approval_ttl_seconds=settings.approval_ttl_seconds,
    )
    minted = approvals.idempotency_key_for(cart.id, cart.version)
    key = minted or case.get("idempotency_key", f"eval-unissued-{uuid.uuid4()}")

    attempts = 2 if case.get("replay", False) else 1
    outcome: dict[str, Any] = {"created": False}
    policy: dict[str, Any] | None = None
    order_ids: list[str] = []
    for _ in range(attempts):
        try:
            result = service.create_order(
                merchant_id=merchant_id,
                session_id=session_id,
                cart_id=cart.id,
                cart_version=cart.version,
                idempotency_key=key,
            )
        except OrderError as error:
            codes = error.details.get("reason_codes", [])
            outcome = {
                "created": False,
                "code": error.code,
                "message": error.message,
                "reason_codes": codes,
                "validated_total": error.details.get("validated_total"),
                "key_was_issued_by_the_application": minted is not None,
            }
            # The refusal *is* the Policy Engine's verdict when the code says so.
            # Reading it from here rather than re-evaluating keeps exactly one
            # assembly of the transaction context in the system: the real one.
            if error.code == "POLICY_FAILED":
                policy = {
                    "decision": "FAIL",
                    "reason_codes": codes,
                    "validated_total": error.details.get("validated_total"),
                }
            break
        order_ids.append(str(result.order_id))
        order = service.get(merchant_id, result.order_id)
        decision = result.decision
        policy = (
            None
            if decision is None
            else {
                "decision": decision.decision,
                "reason_codes": [code.value for code in decision.reason_codes],
                "validated_total": str(decision.validated_total),
            }
        )
        outcome = {
            "created": True,
            "order_id": str(result.order_id),
            "status": order.status if order else None,
            "total": str(order.total_amount) if order else None,
            "razorpay_order_id": order.razorpay_order_id if order else None,
            "key_was_issued_by_the_application": minted is not None,
        }
    return {
        "policy": policy,
        "order_outcome": outcome,
        "order_ids": order_ids,
        "order": (
            None
            if not outcome.get("created")
            else {
                "total": outcome["total"],
                "lines": [{"sku": item.sku, "quantity": item.quantity} for item in cart.items],
            }
        ),
    }
