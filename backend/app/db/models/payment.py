"""``payments``, ``webhook_events`` and ``audit_events`` — ADR-006, ADR-012.

**Rows in `payments` are written only by verified webhook processing** (ADR-012).
Not by the checkout flow, not by a buyer telling the agent they paid, not by a
frontend callback. A verified Razorpay webhook owns whether money moved; nothing
else in this system has an opinion worth storing.

**`webhook_events.raw_body` holds the request exactly as received, captured
before parsing** (P§24). Signature verification runs against those bytes, which
is why the route that receives them must not bind a Pydantic body model — a
re-serialized body is a different byte sequence and would verify against nothing.

**Deduplication is `UNIQUE(provider, event_id)`, not a read-then-write check**
(P§25, P§26). At-least-once delivery will eventually find the race in a
check-then-insert; a unique constraint has none.

**`audit_events` is append-only.** No `updated_at`, no update path in the
repository, and in a deployed environment the application's role is granted
`INSERT` and `SELECT` on this table only. `seq` exists because timestamps tie:
two events in the same transaction can share a microsecond, and a total order is
what makes a transaction reconstructable.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, CurrencyCode, Money, TimestampMixin, uuid_pk
from app.db.models._enums import in_list
from app.domain.commerce import (
    AUDIT_ACTORS,
    AUDIT_EVENT_TYPES,
    PAYMENT_STATUSES,
    WEBHOOK_STATUSES,
    WebhookStatus,
)

if TYPE_CHECKING:
    from app.db.models.order import Order


class Payment(Base, TimestampMixin):
    """What the provider says happened to the money."""

    __tablename__ = "payments"
    __table_args__ = (
        UniqueConstraint("razorpay_payment_id"),
        CheckConstraint(in_list("status", PAYMENT_STATUSES), name="status_is_known"),
        CheckConstraint("amount >= 0", name="amount_is_not_negative"),
        CheckConstraint("amount_minor >= 0", name="amount_minor_is_not_negative"),
        Index("ix_payments_order_id", "order_id"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    order_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("orders.id"), nullable=False
    )
    razorpay_payment_id: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Money, nullable=False)
    #: As reported by Razorpay, in minor units. Kept alongside the decimal so a
    #: disagreement between what they charged and what we recorded is visible
    #: rather than hidden by a conversion (ADR-008).
    amount_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    currency: Mapped[str] = mapped_column(CurrencyCode, nullable=False)
    method: Mapped[str | None] = mapped_column(String(32), nullable=True)
    #: Internal only. F§25: never rendered raw to a buyer.
    failure_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    order: Mapped[Order] = relationship()

    def __repr__(self) -> str:
        return f"<Payment {self.razorpay_payment_id} {self.status}>"


class WebhookEvent(Base):
    """One delivery from the provider, recorded before it is trusted."""

    __tablename__ = "webhook_events"
    __table_args__ = (
        # The deduplication key. Enforced by the database so two concurrent
        # deliveries of one event cannot both proceed (P§25, P§26).
        UniqueConstraint("provider", "event_id"),
        CheckConstraint(in_list("status", WEBHOOK_STATUSES), name="status_is_known"),
        Index("ix_webhook_events_order_id", "order_id"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    provider: Mapped[str] = mapped_column(
        String(24), nullable=False, server_default=text("'razorpay'")
    )
    event_id: Mapped[str] = mapped_column(String(128), nullable=False)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    signature: Mapped[str] = mapped_column(String(256), nullable=False)
    #: Exactly as received, before parsing (P§24). Verification runs against
    #: these bytes.
    raw_body: Mapped[str] = mapped_column(Text, nullable=False)
    #: Parsed, and only after verification succeeded.
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default=text(f"'{WebhookStatus.RECEIVED.value}'")
    )
    #: Nullable: an event may arrive before this system knows the order it names
    #: (P§27), and refusing to record it would lose the only copy.
    order_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("orders.id"), nullable=True
    )
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    order: Mapped[Order | None] = relationship()

    def __repr__(self) -> str:
        return f"<WebhookEvent {self.provider}:{self.event_id} {self.status}>"


class AuditEvent(Base):
    """One append-only fact about how a transaction reached its outcome."""

    __tablename__ = "audit_events"
    __table_args__ = (
        UniqueConstraint("seq"),
        CheckConstraint(in_list("event_type", AUDIT_EVENT_TYPES), name="event_type_is_known"),
        CheckConstraint(in_list("actor", AUDIT_ACTORS), name="actor_is_known"),
        CheckConstraint("jsonb_typeof(payload) = 'object'", name="payload_is_an_object"),
        Index("ix_audit_events_session_id", "session_id"),
        Index("ix_audit_events_order_id", "order_id"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    #: A total order. Timestamps tie — two events in one transaction can share a
    #: microsecond — and "what happened next" is the question an audit asks.
    seq: Mapped[int] = mapped_column(BigInteger, Identity(always=False), nullable=False)
    event_type: Mapped[str] = mapped_column(String(48), nullable=False)
    actor: Mapped[str] = mapped_column(String(16), nullable=False)
    #: All four nullable: not every event has a cart, an order or a payment.
    session_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("sessions.id"), nullable=True
    )
    cart_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("carts.id"), nullable=True
    )
    order_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("orders.id"), nullable=True
    )
    payment_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("payments.id"), nullable=True
    )
    #: Never contains a secret (L§45, ADR-006).
    payload: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    def __repr__(self) -> str:
        return f"<AuditEvent {self.seq} {self.event_type} by {self.actor}>"
