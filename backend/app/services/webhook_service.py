"""Webhook processing — the only thing that decides a payment happened (M12).

ADR-012, P§22–P§28. Every rule here exists because a payment webhook is an
*untrusted HTTP request until it is verified*, and because the network will
deliver it more than once, out of order, and sometimes before the order it names
exists.

**Verification runs against the raw bytes.** The route captures
`await request.body()` before anything parses it, and parsing happens only after
the HMAC matches. `json.loads` followed by `json.dumps` does not reproduce the
original bytes, so a signature checked against re-serialized JSON proves nothing
(P§24).

**The comparison is constant-time.** `hmac.compare_digest`, because a byte-by-byte
comparison that returns early leaks the signature through timing.

**Deduplication is a `UNIQUE` constraint, not a lookup.** Two simultaneous
deliveries of one event would both pass a "have I seen this?" query (P§25, P§26).
The insert is attempted and the violation is caught.

**Handlers are idempotent state assertions, not increments** (P§27). Applying the
same event twice, or a late-arriving earlier event after a later one, converges
on the same state — and nothing ever moves backwards out of `PAYMENT_CONFIRMED`.

**`200` is the default answer.** Razorpay retries anything else, and a duplicate,
an unknown event type and an event for an unknown order are all *correctly
handled* outcomes. `400` is reserved for a failed signature; `500` for a genuine
internal fault, where a retry is actually wanted.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session as DbSession

from app.db.models import Order, Payment, WebhookEvent
from app.domain.commerce import OrderStatus, PaymentStatus, WebhookStatus
from app.payments.money import from_minor_units
from app.services.audit_service import AuditService

logger = logging.getLogger(__name__)

__all__ = [
    "SUBSCRIBED_EVENTS",
    "WebhookOutcome",
    "WebhookService",
    "WebhookSignatureError",
    "verify_signature",
]

#: The three events this application acts on (ADR-012, closing D7). Every other
#: type is *stored* with status IGNORED and answered 200 — recorded, not acted
#: on. Silently discarding an unknown event would make a future subscription
#: change invisible.
SUBSCRIBED_EVENTS: frozenset[str] = frozenset({"payment.captured", "payment.failed", "order.paid"})


class WebhookSignatureError(Exception):
    """The request did not come from the provider, or was altered in flight.

    An unverified webhook is not a webhook; it is an anonymous HTTP request
    (P§23). Nothing about payment state is touched.
    """


def verify_signature(raw_body: bytes, signature: str | None, secret: str) -> None:
    """HMAC-SHA256 over the raw bytes, compared in constant time.

    Raises rather than returning a bool, so a caller cannot forget to check the
    result — the failure path is the one that must never be skipped.
    """
    if not signature:
        raise WebhookSignatureError("no signature header was supplied")
    if not secret:
        raise WebhookSignatureError("no webhook secret is configured")

    expected = hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, signature):
        raise WebhookSignatureError("the signature does not match the body")


@dataclass(frozen=True, slots=True)
class WebhookOutcome:
    """What became of one delivery.

    `handled` is false for a duplicate, an unknown type and an unknown order —
    all of which are correct outcomes answered with `200`. The distinction
    matters for the audit trail (M13) rather than for the status code.
    """

    status: WebhookStatus
    event_id: str
    order_id: Any = None
    detail: str = ""

    @property
    def handled(self) -> bool:
        return self.status is WebhookStatus.PROCESSED


class WebhookService:
    """Records and applies verified provider events."""

    def __init__(self, session: DbSession) -> None:
        self._session = session
        self._audit = AuditService(session)

    def process(
        self, raw_body: bytes, signature: str | None, secret: str, *, provider: str = "razorpay"
    ) -> WebhookOutcome:
        """Verify, record, and apply. Raises only on a bad signature.

        The order is deliberate: verification first, because an unverified body
        must not even be parsed; recording second, because the stored row is what
        makes reconciliation possible; applying last, because a handler that
        failed must not lose the evidence that the event arrived.
        """
        verify_signature(raw_body, signature, secret)

        payload = self._parse(raw_body)
        event_id = self._event_id(payload, raw_body)
        event_type = str(payload.get("event", "")) or "unknown"

        event = self._record(provider, event_id, event_type, signature or "", raw_body, payload)
        if event is None:
            # The UNIQUE constraint caught a duplicate. Answered 200: it was
            # already handled, and Razorpay retrying is expected behaviour.
            self._audit.webhook_duplicate_ignored(event_id=event_id)
            logger.info("duplicate webhook ignored", extra={"event_id": event_id})
            return WebhookOutcome(WebhookStatus.IGNORED, event_id, detail="duplicate")

        if event_type not in SUBSCRIBED_EVENTS:
            event.status = WebhookStatus.IGNORED.value
            event.processed_at = datetime.now(UTC)
            self._session.flush()
            return WebhookOutcome(WebhookStatus.IGNORED, event_id, detail="unsubscribed")

        order = self._find_order(payload)
        # Recorded *after* the lookup so the row can carry the order id, which
        # is what makes a delivery part of that order's reconstruction rather
        # than an orphan in the log. It is still written when the order is
        # unknown - the arrival is a fact either way (P§27).
        self._audit.payment_webhook_received(
            event_id=event_id,
            event_type=event_type,
            order_id=None if order is None else order.id,
        )

        if order is None:
            # P§27: an event may arrive before its order is committed, or belong
            # to another system sharing the account. Never dropped - the stored
            # row is what a reconciliation reads.
            logger.info("webhook for an unknown order", extra={"event_id": event_id})
            return WebhookOutcome(WebhookStatus.RECEIVED, event_id, detail="unknown order")

        event.order_id = order.id
        self._apply(event_type, payload, order)
        self._audit_outcome(event_type, payload, order)
        event.status = WebhookStatus.PROCESSED.value
        event.processed_at = datetime.now(UTC)
        self._session.flush()

        logger.info(
            "webhook processed",
            extra={"event_id": event_id, "event_type": event_type, "order_id": str(order.id)},
        )
        return WebhookOutcome(WebhookStatus.PROCESSED, event_id, order_id=order.id)

    def _audit_outcome(self, event_type: str, payload: dict[str, Any], order: Order) -> None:
        """Record what the provider said happened to the money.

        Attributed to `RAZORPAY`, because the provider caused it - not a user
        and not the agent. That distinction is the whole reason the actor column
        exists: a reconstruction has to be able to say who did what.
        """
        entity = self._payment_entity(payload)
        razorpay_payment_id = str(entity.get("id") or "")
        if not razorpay_payment_id:
            return

        payment = self._session.execute(
            select(Payment).where(Payment.razorpay_payment_id == razorpay_payment_id)
        ).scalar_one_or_none()
        payment_id = None if payment is None else payment.id

        if event_type in ("payment.captured", "order.paid"):
            self._audit.payment_confirmed(
                order.id, payment_id=payment_id, razorpay_payment_id=razorpay_payment_id
            )
        elif event_type == "payment.failed":
            self._audit.payment_failed(
                order.id,
                payment_id=payment_id,
                razorpay_payment_id=razorpay_payment_id,
                # Recorded here and never rendered to a buyer (F§25). The log
                # is where an operator reads it.
                reason=entity.get("error_description"),
            )

    # -- recording -----------------------------------------------------------

    def _record(
        self,
        provider: str,
        event_id: str,
        event_type: str,
        signature: str,
        raw_body: bytes,
        payload: dict[str, Any],
    ) -> WebhookEvent | None:
        """Insert the event, or `None` if it is a duplicate.

        A `SAVEPOINT` around the insert so the unique violation does not poison
        the outer transaction — the caller still has work to do, and a duplicate
        is a normal outcome rather than a failure.
        """
        event = WebhookEvent(
            provider=provider,
            event_id=event_id,
            event_type=event_type,
            signature=signature,
            raw_body=raw_body.decode("utf-8", errors="replace"),
            payload=payload,
            status=WebhookStatus.RECEIVED.value,
        )
        try:
            with self._session.begin_nested():
                self._session.add(event)
                self._session.flush()
        except IntegrityError:
            return None
        return event

    # -- applying ------------------------------------------------------------

    def _apply(self, event_type: str, payload: dict[str, Any], order: Order) -> None:
        """Assert a state rather than advance one (P§27).

        Nothing here reads the order's current status in order to decide *what*
        to do next; each handler states what must be true and refuses only the
        one transition that would move backwards.
        """
        entity = self._payment_entity(payload)

        if event_type == "payment.captured":
            self._upsert_payment(order, entity, PaymentStatus.CAPTURED)
            order.status = OrderStatus.PAYMENT_CONFIRMED.value

        elif event_type == "payment.failed":
            self._upsert_payment(order, entity, PaymentStatus.FAILED)
            if order.status == OrderStatus.PAYMENT_CONFIRMED.value:
                # A late failure for an order already confirmed by a capture.
                # Logged and ignored: money that arrived does not un-arrive
                # because an earlier attempt's failure was delivered slowly.
                logger.warning(
                    "payment.failed for a confirmed order; state unchanged",
                    extra={"order_id": str(order.id)},
                )
            else:
                order.status = OrderStatus.PAYMENT_FAILED.value

        elif event_type == "order.paid":
            if order.status != OrderStatus.PAYMENT_CONFIRMED.value:
                order.status = OrderStatus.PAYMENT_CONFIRMED.value

    def _upsert_payment(
        self, order: Order, entity: dict[str, Any], status: PaymentStatus
    ) -> Payment | None:
        """Record what the provider says about the money.

        Rows in `payments` are written **only** from here — never by the checkout
        flow, never by a buyer telling the agent they paid, never by a frontend
        callback.
        """
        payment_id = entity.get("id")
        if not payment_id:
            return None

        existing = self._session.execute(
            select(Payment).where(Payment.razorpay_payment_id == str(payment_id))
        ).scalar_one_or_none()

        minor = int(entity.get("amount") or order.total_amount_minor)
        currency = str(entity.get("currency") or order.currency)

        if existing is not None:
            # Idempotent: the same event twice sets the same values.
            existing.status = status.value
            existing.failure_reason = entity.get("error_description")
            return existing

        payment = Payment(
            order_id=order.id,
            razorpay_payment_id=str(payment_id),
            status=status.value,
            amount=from_minor_units(minor, currency),
            amount_minor=minor,
            currency=currency,
            method=entity.get("method"),
            # Internal only. F§25: never rendered raw to a buyer.
            failure_reason=entity.get("error_description"),
        )
        self._session.add(payment)
        self._session.flush()
        return payment

    # -- reading the payload -------------------------------------------------

    @staticmethod
    def _parse(raw_body: bytes) -> dict[str, Any]:
        try:
            payload = json.loads(raw_body)
        except (ValueError, UnicodeDecodeError) as exc:
            raise WebhookSignatureError("the verified body is not JSON") from exc
        if not isinstance(payload, dict):
            raise WebhookSignatureError("the verified body is not a JSON object")
        return payload

    @staticmethod
    def _event_id(payload: dict[str, Any], raw_body: bytes) -> str:
        """Razorpay's event id, or a digest of the body.

        The header `X-Razorpay-Event-Id` is the documented identifier, and the
        payload carries one too. Falling back to a digest of the raw body keeps
        deduplication working for a delivery that carries neither, rather than
        letting such an event be processed repeatedly.
        """
        for key in ("id", "event_id"):
            value = payload.get(key)
            if isinstance(value, str) and value:
                return value
        return hashlib.sha256(raw_body).hexdigest()

    @staticmethod
    def _payment_entity(payload: dict[str, Any]) -> dict[str, Any]:
        entity = payload.get("payload", {}).get("payment", {}).get("entity", {})
        return entity if isinstance(entity, dict) else {}

    def _find_order(self, payload: dict[str, Any]) -> Order | None:
        """The local order this event is about, by provider order id.

        `None` is a normal outcome, not an error: the event may have arrived
        before the order was committed, or belong to another system sharing the
        provider account.
        """
        candidates: list[str] = []
        for section in ("payment", "order"):
            entity = payload.get("payload", {}).get(section, {}).get("entity", {})
            if isinstance(entity, dict):
                for key in ("order_id", "id"):
                    value = entity.get(key)
                    if isinstance(value, str) and value.startswith("order_"):
                        candidates.append(value)

        for razorpay_order_id in candidates:
            order = self._session.execute(
                select(Order).where(Order.razorpay_order_id == razorpay_order_id)
            ).scalar_one_or_none()
            if order is not None:
                return order
        return None
