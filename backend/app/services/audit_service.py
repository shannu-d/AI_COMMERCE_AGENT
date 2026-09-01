"""The Audit Service (M13; ADR-006, A§39, A§40, RZP-07).

The durable record of how a transaction reached its outcome. A§40 draws the
distinction this service exists on one side of:

* the **agent trace** is per turn, returned in the response, and never persisted
  (ADR-010, closing E6) — it explains one conversation to a developer;
* the **audit log** is durable, append-only, and explains a *transaction* to
  whoever asks afterwards.

**One named method per event type**, rather than a generic `record(type, ...)`.
Sixteen small methods look repetitive and are the point: each names exactly what
must be captured for that event, so a call site cannot omit the cart id from a
`CART_CREATED` or the reason codes from a `POLICY_FAIL`. A generic writer would
put that responsibility on every caller and lose it at the first hurried one.

**Nothing here can change an outcome.** The service writes rows and returns them.
It has no way to alter an order, a payment or an approval, which is why it is the
last thing added to the money path rather than the first: an audit writer that
could affect what it records would be a poor audit writer.

**No secret is ever written** (L§45, ADR-006). Payloads carry identifiers,
amounts as strings, reason codes and status values — never a key, never a
signature, never a raw provider body.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Sequence
from decimal import Decimal
from typing import Any

from sqlalchemy.orm import Session as DbSession

from app.db.models import AuditEvent
from app.domain.commerce import AuditActor, AuditEventType
from app.repositories.audit_repository import AuditRepository

logger = logging.getLogger(__name__)

__all__ = ["AuditService"]


def _money(amount: Decimal | None) -> str | None:
    """Amounts are strings in a payload, for the same reason they are on the
    wire (ADR-008): JSONB would store a float and lose the paisa."""
    return None if amount is None else str(amount)


class AuditService:
    """Writes the twelve events RZP-07 names, and the four the failures need."""

    def __init__(self, session: DbSession) -> None:
        self._events = AuditRepository(session)

    # -- cart and approval ---------------------------------------------------

    def cart_created(self, session_id: uuid.UUID, cart_id: uuid.UUID) -> AuditEvent:
        return self._events.append(
            AuditEventType.CART_CREATED,
            AuditActor.AGENT,
            session_id=session_id,
            cart_id=cart_id,
        )

    def user_approved(
        self,
        session_id: uuid.UUID,
        cart_id: uuid.UUID,
        *,
        approval_id: uuid.UUID,
        cart_version: int,
        approved_total: Decimal,
        currency: str,
    ) -> AuditEvent:
        """The single most important row in the log.

        `USER`, never `AGENT`: this is the record that a human authorized a
        payment, and attributing it to anything else would make the log disagree
        with the architecture it is supposed to evidence (ADR-007).
        """
        return self._events.append(
            AuditEventType.USER_APPROVED,
            AuditActor.USER,
            session_id=session_id,
            cart_id=cart_id,
            payload={
                "approval_id": str(approval_id),
                "cart_version": cart_version,
                "approved_total": _money(approved_total),
                "currency": currency,
            },
        )

    def approval_superseded(
        self, cart_id: uuid.UUID, *, approval_id: uuid.UUID, reason: str
    ) -> AuditEvent:
        """One of the four events added beyond RZP-07's twelve.

        Without it, an approval that vanished between two reads is
        unexplainable - and the price-drift scenario is exactly a story about an
        approval vanishing.
        """
        return self._events.append(
            AuditEventType.APPROVAL_SUPERSEDED,
            AuditActor.SYSTEM,
            cart_id=cart_id,
            payload={"approval_id": str(approval_id), "reason": reason},
        )

    def approval_expired(self, cart_id: uuid.UUID, *, approval_id: uuid.UUID) -> AuditEvent:
        return self._events.append(
            AuditEventType.APPROVAL_EXPIRED,
            AuditActor.SYSTEM,
            cart_id=cart_id,
            payload={"approval_id": str(approval_id)},
        )

    # -- policy --------------------------------------------------------------

    def policy_pass(
        self, cart_id: uuid.UUID, *, validated_total: Decimal, currency: str
    ) -> AuditEvent:
        return self._events.append(
            AuditEventType.POLICY_PASS,
            AuditActor.SYSTEM,
            cart_id=cart_id,
            payload={"validated_total": _money(validated_total), "currency": currency},
        )

    def policy_fail(
        self,
        cart_id: uuid.UUID,
        *,
        reason_codes: Sequence[str],
        validated_total: Decimal,
        currency: str,
    ) -> AuditEvent:
        """The reason codes are the payload's whole point.

        A `POLICY_FAIL` without them records that something was refused and not
        what was wrong, which is the half a reconstruction needs.
        """
        return self._events.append(
            AuditEventType.POLICY_FAIL,
            AuditActor.SYSTEM,
            cart_id=cart_id,
            payload={
                "reason_codes": list(reason_codes),
                "validated_total": _money(validated_total),
                "currency": currency,
            },
        )

    def price_changed(
        self,
        cart_id: uuid.UUID,
        *,
        previous_total: Decimal,
        current_total: Decimal,
        currency: str,
    ) -> AuditEvent:
        """Both figures, because "the price changed" is not a fact anyone can act
        on without knowing from what, to what."""
        return self._events.append(
            AuditEventType.PRICE_CHANGED,
            AuditActor.SYSTEM,
            cart_id=cart_id,
            payload={
                "previous_total": _money(previous_total),
                "current_total": _money(current_total),
                "currency": currency,
            },
        )

    def inventory_failure(self, cart_id: uuid.UUID, *, sku: str, requested: int) -> AuditEvent:
        """The SKU and the quantity asked for. Not the stock level: a merchant's
        position is not written into a record read during support (ADR-009,
        closing E5)."""
        return self._events.append(
            AuditEventType.INVENTORY_FAILURE,
            AuditActor.SYSTEM,
            cart_id=cart_id,
            payload={"sku": sku, "requested_quantity": requested},
        )

    # -- orders and payments -------------------------------------------------

    def order_created(
        self,
        order_id: uuid.UUID,
        *,
        session_id: uuid.UUID,
        cart_id: uuid.UUID,
        total_amount: Decimal,
        currency: str,
    ) -> AuditEvent:
        return self._events.append(
            AuditEventType.ORDER_CREATED,
            AuditActor.SYSTEM,
            session_id=session_id,
            cart_id=cart_id,
            order_id=order_id,
            payload={"total_amount": _money(total_amount), "currency": currency},
        )

    def razorpay_order_created(
        self, order_id: uuid.UUID, *, razorpay_order_id: str, amount_minor: int
    ) -> AuditEvent:
        return self._events.append(
            AuditEventType.RAZORPAY_ORDER_CREATED,
            AuditActor.SYSTEM,
            order_id=order_id,
            payload={"razorpay_order_id": razorpay_order_id, "amount_minor": amount_minor},
        )

    def checkout_started(self, order_id: uuid.UUID) -> AuditEvent:
        return self._events.append(
            AuditEventType.CHECKOUT_STARTED, AuditActor.USER, order_id=order_id
        )

    def payment_webhook_received(
        self, *, event_id: str, event_type: str, order_id: uuid.UUID | None = None
    ) -> AuditEvent:
        """`RAZORPAY` is the actor: the provider caused this, not a user and not
        the agent."""
        return self._events.append(
            AuditEventType.PAYMENT_WEBHOOK_RECEIVED,
            AuditActor.RAZORPAY,
            order_id=order_id,
            payload={"event_id": event_id, "event_type": event_type},
        )

    def payment_confirmed(
        self, order_id: uuid.UUID, *, payment_id: uuid.UUID | None, razorpay_payment_id: str
    ) -> AuditEvent:
        return self._events.append(
            AuditEventType.PAYMENT_CONFIRMED,
            AuditActor.RAZORPAY,
            order_id=order_id,
            payment_id=payment_id,
            payload={"razorpay_payment_id": razorpay_payment_id},
        )

    def payment_failed(
        self,
        order_id: uuid.UUID,
        *,
        payment_id: uuid.UUID | None,
        razorpay_payment_id: str,
        reason: str | None = None,
    ) -> AuditEvent:
        """The provider's reason is recorded here and never rendered to a buyer
        (F§25). The log is where an operator reads it."""
        return self._events.append(
            AuditEventType.PAYMENT_FAILED,
            AuditActor.RAZORPAY,
            order_id=order_id,
            payment_id=payment_id,
            payload={"razorpay_payment_id": razorpay_payment_id, "reason": reason},
        )

    def webhook_signature_rejected(self, *, event_type: str | None = None) -> AuditEvent:
        """No order id, because an unverified request names nothing this
        application is entitled to believe (P§23). The signature itself is never
        written down."""
        return self._events.append(
            AuditEventType.WEBHOOK_SIGNATURE_REJECTED,
            AuditActor.SYSTEM,
            payload={"event_type": event_type} if event_type else {},
        )

    def webhook_duplicate_ignored(self, *, event_id: str) -> AuditEvent:
        return self._events.append(
            AuditEventType.WEBHOOK_DUPLICATE_IGNORED,
            AuditActor.SYSTEM,
            payload={"event_id": event_id},
        )

    # -- reading -------------------------------------------------------------

    def reconstruct_order(self, order_id: uuid.UUID) -> list[dict[str, Any]]:
        """Everything that happened to one order, in order.

        M13's exit condition is that a full transaction is reconstructable from
        the audit events, and this is the read that does it.
        """
        return [
            {
                "seq": event.seq,
                "event_type": event.event_type,
                "actor": event.actor,
                "payload": dict(event.payload or {}),
                "created_at": event.created_at.isoformat(),
            }
            for event in self._events.for_order(order_id)
        ]

    def reconstruct_session(self, session_id: uuid.UUID) -> list[dict[str, Any]]:
        return [
            {
                "seq": event.seq,
                "event_type": event.event_type,
                "actor": event.actor,
                "payload": dict(event.payload or {}),
                "created_at": event.created_at.isoformat(),
            }
            for event in self._events.for_session(session_id)
        ]
