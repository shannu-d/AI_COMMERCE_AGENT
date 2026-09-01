"""The Order Service (M10; ADR-011, ADR-013, P§14–P§18).

**The only code in this system that creates an order**, and the only place the
Policy Engine is invoked. ADR-011's ten steps, in one method:

    1. load the session, the cart and its APPROVED approval
    2. BEGIN
    3. re-read authoritative prices from `product_variants`        <- live
    4. SELECT ... FOR UPDATE the inventory rows for every line     <- live, locked
    5. PolicyEngine.evaluate(TransactionContext) -> PolicyDecision
    6. FAIL  -> mark the key FAILED, return reason codes. No provider call.
    7. PASS  -> insert orders + order_items, mark the key COMPLETED
    8. COMMIT                                                       <- the order exists
    9. call Razorpay                                                <- M11
   10. audit                                                        <- M13

Steps 9 and 10 are later milestones and their absence is deliberate rather than
pending: an order sitting in `ORDER_CREATED` with a null `razorpay_order_id` is
exactly the state ADR-011 designs for, because the internal order is committed
*before* the provider is called. The reverse ordering would allow a provider
order with no local record, which is unreconcilable.

**Nothing from the client is authoritative.** The route accepts a session, a
cart, a claimed `cart_version` and an idempotency key. It accepts no amount, no
price, no item list and no currency: F§17's forged `amount = 1` is not rejected
by validation, it has nowhere to be submitted. Every monetary value below is
recomputed from the database inside the transaction.

**Freshness is the point of steps 3 and 4.** They read `product_variants.price`
and `inventory` at evaluation time. They never read
`cart_items.unit_price_snapshot`, never a value cached earlier in the request,
and never anything the model supplied. RULE 12 and P§11 both require it, and it
is the mechanism that makes the price-drift scenario work.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from app.db.models import Cart, IdempotencyKey, Inventory, Order, OrderItem, ProductVariant
from app.domain.approval import FingerprintLine, items_fingerprint
from app.domain.commerce import (
    ApprovalStatus,
    CartStatus,
    IdempotencyStatus,
    OrderStatus,
)
from app.domain.policy import LineContext, PolicyDecision, TransactionContext
from app.payments.money import to_minor_units
from app.policy import PolicyEngine
from app.repositories.cart_repository import CartRepository
from app.services.approval_service import ApprovalService
from app.services.audit_service import AuditService

logger = logging.getLogger(__name__)

__all__ = ["OrderError", "OrderResult", "OrderService"]


class OrderError(Exception):
    """An order that cannot be created, with a code the route maps to a status."""

    def __init__(self, code: str, message: str, *, details: dict | None = None) -> None:
        self.code = code
        self.message = message
        self.details = details or {}
        super().__init__(f"{code}: {message}")


@dataclass(frozen=True, slots=True)
class OrderResult:
    """What one order attempt produced.

    A *replay* is a first-class outcome rather than an error: presenting a spent
    key returns the stored response verbatim, which is the whole promise of
    idempotency (P§15, P§34).
    """

    order_id: uuid.UUID
    status: OrderStatus
    total_amount: Decimal
    total_amount_minor: int
    currency: str
    decision: PolicyDecision | None = None
    #: True when this call returned a previous call's answer rather than doing
    #: the work again.
    replayed: bool = False


class OrderService:
    """Creates orders. Nothing else may."""

    def __init__(
        self,
        session: DbSession,
        *,
        spending_limit: Decimal,
        spending_limit_currency: str = "INR",
        approval_ttl_seconds: int = 900,
    ) -> None:
        self._session = session
        self._carts = CartRepository(session)
        self._approvals = ApprovalService(session, ttl_seconds=approval_ttl_seconds)
        self._audit = AuditService(session)
        self._policy = PolicyEngine(
            spending_limit=spending_limit, spending_limit_currency=spending_limit_currency
        )

    # -- the one path to an order -------------------------------------------

    def create_order(
        self,
        merchant_id: uuid.UUID,
        session_id: uuid.UUID,
        cart_id: uuid.UUID,
        cart_version: int,
        idempotency_key: str,
    ) -> OrderResult:
        """ADR-011 steps 1 through 8. Raises `OrderError` on any refusal."""
        key = self._claim_key(idempotency_key, session_id)
        if key is None:
            # Another request holds the row. A race lost cleanly, not resolved
            # by whoever arrives second (ADR-013).
            raise OrderError(
                "ORDER_IN_PROGRESS",
                "this order is already being created; please wait a moment",
            )

        replay = self._replay_if_spent(key)
        if replay is not None:
            return replay

        # 1-4. Load everything live, with the inventory rows locked.
        cart = self._carts.for_update(merchant_id, cart_id)
        if cart is None or cart.session_id != session_id:
            self._fail_key(key)
            raise OrderError("VALIDATION_ERROR", "no such cart for this session")

        lines = self._live_lines(merchant_id, cart)
        approval = self._approvals.current(cart_id)
        context = self._context(merchant_id, session_id, cart, cart_version, lines, approval, key)

        # 5. Evaluate.
        decision = self._policy.evaluate(context)

        # 6. FAIL: no order, no provider call, and the key is spent.
        if not decision.passed:
            self._fail_key(key)
            self._audit_refusal(cart, decision, context)
            logger.info(
                "order refused by policy",
                extra={
                    "cart_id": str(cart_id),
                    "reason_codes": [code.value for code in decision.reason_codes],
                },
            )
            raise OrderError(
                "POLICY_FAILED",
                "this purchase cannot be completed",
                details={
                    "reason_codes": [code.value for code in decision.reason_codes],
                    "validated_total": str(decision.validated_total),
                    "currency": decision.currency,
                    **decision.details,
                },
            )

        # 7. PASS: insert the order and its immutable lines.
        order = self._insert_order(merchant_id, session_id, cart, decision, key, lines)
        self._audit.policy_pass(
            cart.id, validated_total=decision.validated_total, currency=decision.currency
        )
        self._audit.order_created(
            order.id,
            session_id=session_id,
            cart_id=cart.id,
            total_amount=order.total_amount,
            currency=order.currency,
        )
        cart.status = CartStatus.ORDERED.value
        self._complete_key(key, order)
        self._session.flush()

        logger.info(
            "order created",
            extra={"order_id": str(order.id), "total": str(order.total_amount)},
        )
        return OrderResult(
            order_id=order.id,
            status=OrderStatus(order.status),
            total_amount=order.total_amount,
            total_amount_minor=order.total_amount_minor,
            currency=order.currency,
            decision=decision,
        )

    # -- reads ---------------------------------------------------------------

    def attach_provider_order(
        self, merchant_id: uuid.UUID, order_id: uuid.UUID, client: Any
    ) -> Order:
        """ADR-011 step 9, **after** the internal order is committed.

        Deliberately a separate method rather than the tail of `create_order`,
        because the ordering is the guarantee: the internal order exists and is
        committed before a provider is reached. A failure here therefore leaves
        the order in `ORDER_CREATED` with a null `razorpay_order_id` - a visible,
        retryable, auditable state - rather than rolling back a purchase the
        buyer authorized.

        Retrying reuses this same internal order and the same idempotency key,
        so a network failure cannot produce two provider orders (ADR-013).
        """
        order = self.get(merchant_id, order_id)
        if order is None:
            raise OrderError("VALIDATION_ERROR", "no such order")
        if order.razorpay_order_id is not None:
            return order  # already attached; retrying is a no-op, not an error

        provider_id = client.create_order(order)
        order.razorpay_order_id = provider_id
        order.status = OrderStatus.RAZORPAY_ORDER_CREATED.value
        self._audit.razorpay_order_created(
            order.id,
            razorpay_order_id=provider_id,
            amount_minor=order.total_amount_minor,
        )
        self._session.flush()
        logger.info(
            "provider order attached",
            extra={"order_id": str(order.id), "razorpay_order_id": provider_id},
        )
        return order

    def get(self, merchant_id: uuid.UUID, order_id: uuid.UUID) -> Order | None:
        return self._session.execute(
            select(Order).where(Order.id == order_id, Order.merchant_id == merchant_id)
        ).scalar_one_or_none()

    def _audit_refusal(self, cart, decision, context) -> None:
        """Record *why* a purchase was refused, not merely that it was.

        A POLICY_FAIL alone says something was wrong. The two events beside it
        say what: PRICE_CHANGED carries both totals, because "the price
        changed" is not actionable without knowing from what to what, and
        INVENTORY_FAILURE names the SKU. Between them a reconstruction can
        explain the refusal to a buyer months later.
        """
        from app.domain.policy import ReasonCode

        self._audit.policy_fail(
            cart.id,
            reason_codes=[code.value for code in decision.reason_codes],
            validated_total=decision.validated_total,
            currency=decision.currency,
        )
        if ReasonCode.PRICE_CHANGED in decision.reason_codes:
            self._audit.price_changed(
                cart.id,
                previous_total=context.approved_total or decision.validated_total,
                current_total=decision.validated_total,
                currency=decision.currency,
            )
        if ReasonCode.OUT_OF_STOCK in decision.reason_codes:
            for line in context.lines:
                if line.available_quantity < line.quantity:
                    self._audit.inventory_failure(cart.id, sku=line.sku, requested=line.quantity)

    # -- the idempotency key lifecycle (ADR-013) -----------------------------

    def _claim_key(self, value: str, session_id: uuid.UUID) -> IdempotencyKey | None:
        """Take the row lock, or return `None` if another request holds it.

        `FOR UPDATE NOWAIT` rather than a conditional status update, because
        ADR-006 fixes the status column at three values and a key minted at
        approval time is already `RESERVED`. The lock is the mutex ADR-013 asks
        for and is strictly stronger than a compare-and-set: it also serializes
        the read of `response_snapshot` that a replay depends on.
        """
        from sqlalchemy.exc import DBAPIError, OperationalError

        try:
            row = self._session.execute(
                select(IdempotencyKey)
                .where(IdempotencyKey.key == value)
                .with_for_update(nowait=True)
            ).scalar_one_or_none()
        except (OperationalError, DBAPIError):
            self._session.rollback()
            return None

        if row is None:
            raise OrderError(
                "VALIDATION_ERROR",
                "that idempotency key was not issued by this application",
            )
        if row.session_id != session_id:
            raise OrderError("VALIDATION_ERROR", "that idempotency key belongs to another session")
        if row.expires_at <= datetime.now(UTC):
            raise OrderError(
                "APPROVAL_REQUIRED",
                "this checkout has expired; please confirm the cart again",
            )
        return row

    def _replay_if_spent(self, key: IdempotencyKey) -> OrderResult | None:
        """A COMPLETED key returns its stored answer; a FAILED one is terminal.

        A `FAILED` key is never retried: the buyer obtains a fresh approval,
        which mints a fresh key. That is the same recovery path as price drift
        and payment failure, so there is one flow rather than three.
        """
        if key.status == IdempotencyStatus.COMPLETED.value:
            snapshot: dict[str, Any] = key.response_snapshot or {}
            order_id = snapshot.get("order_id")
            if order_id is None:
                raise OrderError("SERVER_ERROR", "a completed request has no stored result")
            return OrderResult(
                order_id=uuid.UUID(order_id),
                status=OrderStatus(snapshot["status"]),
                total_amount=Decimal(snapshot["total_amount"]),
                total_amount_minor=int(snapshot["total_amount_minor"]),
                currency=snapshot["currency"],
                replayed=True,
            )
        if key.status == IdempotencyStatus.FAILED.value:
            raise OrderError(
                "APPROVAL_REQUIRED",
                "this checkout already failed; please confirm the cart again",
            )
        return None

    def _fail_key(self, key: IdempotencyKey) -> None:
        key.status = IdempotencyStatus.FAILED.value
        key.completed_at = datetime.now(UTC)
        self._session.flush()

    def _complete_key(self, key: IdempotencyKey, order: Order) -> None:
        """Store the exact answer a replay will return (ADR-013).

        Money is stored as a string, so a replay produces the same `Decimal` the
        first call did rather than one reconstructed from a JSON float.
        """
        key.status = IdempotencyStatus.COMPLETED.value
        key.completed_at = datetime.now(UTC)
        key.response_snapshot = {
            "order_id": str(order.id),
            "status": order.status,
            "total_amount": str(order.total_amount),
            "total_amount_minor": order.total_amount_minor,
            "currency": order.currency,
        }

    # -- building the policy input -------------------------------------------

    def _live_lines(self, merchant_id: uuid.UUID, cart: Cart) -> list[LineContext]:
        """Steps 3 and 4: live prices, and inventory rows locked for update.

        The lock is what makes two simultaneous checkouts of the last unit
        serialize (ADR-011, closing C6). Without it both would observe stock and
        both would create an order.
        """
        lines: list[LineContext] = []
        for item in self._carts.items(cart.id):
            variant = self._session.execute(
                select(ProductVariant).where(ProductVariant.id == item.variant_id)
            ).scalar_one_or_none()
            if variant is None:
                continue
            inventory = self._session.execute(
                select(Inventory).where(Inventory.variant_id == item.variant_id).with_for_update()
            ).scalar_one_or_none()
            available = 0 if inventory is None else inventory.available_quantity

            lines.append(
                LineContext(
                    variant_id=variant.id,
                    product_id=variant.product_id,
                    sku=variant.sku,
                    quantity=item.quantity,
                    # Live, from `product_variants` — never the snapshot.
                    unit_price=variant.price,
                    currency=variant.currency,
                    available_quantity=available,
                    product_is_active=variant.product.is_active,
                    variant_is_active=variant.is_active,
                    merchant_id=variant.merchant_id,
                )
            )
        return lines

    def _context(
        self, merchant_id, session_id, cart, cart_version, lines, approval, key
    ) -> TransactionContext:
        existing = (
            self._session.execute(
                select(Order.id).where(
                    Order.cart_id == cart.id, Order.status != OrderStatus.CANCELLED.value
                )
            )
            .scalars()
            .all()
        )

        return TransactionContext(
            merchant_id=merchant_id,
            session_id=session_id,
            cart_id=cart.id,
            cart_version=cart_version,
            current_cart_version=cart.version,
            cart_status=cart.status,
            currency=cart.currency,
            lines=tuple(lines),
            approval_id=None if approval is None else approval.id,
            approval_status=None if approval is None else approval.status.value,
            approval_cart_version=None if approval is None else approval.cart_version,
            approved_total=None if approval is None else approval.approved_total,
            approval_currency=None if approval is None else approval.currency,
            approval_fingerprint=None if approval is None else approval.items_fingerprint,
            approval_expires_at=None if approval is None else approval.expires_at,
            approval_superseded=(
                approval is not None and approval.status is not ApprovalStatus.APPROVED
            ),
            # Computed with the one shared function, over the *live* lines - so
            # a swap that kept the total identical is caught (ADR-007).
            current_fingerprint=items_fingerprint(
                FingerprintLine(
                    variant_id=line.variant_id,
                    quantity=line.quantity,
                    unit_price=line.unit_price,
                )
                for line in lines
            ),
            existing_order_ids=tuple(existing),
            idempotency_status=key.status,
            idempotency_key_present=True,
            evaluated_at=datetime.now(UTC),
        )

    # -- writing the order ---------------------------------------------------

    def _insert_order(self, merchant_id, session_id, cart, decision, key, lines) -> Order:
        """Step 7. The order and its immutable lines.

        `total_amount_minor` is computed here rather than at the provider call,
        so what was recorded and what will be charged come from one conversion
        (ADR-008). `order_items` snapshots the SKU and the names: renaming a
        product must not rewrite what somebody bought.
        """
        approval = self._approvals.current(cart.id)
        assert approval is not None  # policy rule 1 passed, so one exists

        total = decision.validated_total
        order = Order(
            merchant_id=merchant_id,
            session_id=session_id,
            cart_id=cart.id,
            cart_version=cart.version,
            approval_id=approval.id,
            idempotency_key_id=key.id,
            status=OrderStatus.ORDER_CREATED.value,
            currency=decision.currency,
            subtotal_amount=total,
            total_amount=total,
            total_amount_minor=to_minor_units(total, decision.currency),
        )
        self._session.add(order)
        self._session.flush()

        for line in lines:
            variant = self._session.execute(
                select(ProductVariant).where(ProductVariant.id == line.variant_id)
            ).scalar_one()
            self._session.add(
                OrderItem(
                    order_id=order.id,
                    variant_id=line.variant_id,
                    sku=line.sku,
                    product_name=variant.product.name,
                    variant_name=variant.name,
                    quantity=line.quantity,
                    unit_price=line.unit_price,
                    line_total=line.line_total,
                    currency=line.currency,
                )
            )
        self._session.flush()
        return order
