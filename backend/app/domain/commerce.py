"""The commerce enumerations, defined once (ADR-006, ADR-007, ADR-011, ADR-012).

ADR-006 requires these to exist in exactly one place: *"the enums are defined
once in Python and rendered into `CHECK` constraints by the migration, so the
application and the database cannot disagree about the legal values."* Every
`CHECK` in migration `0004` is built from a tuple below, and a test compares the
rendered DDL against these, so adding a value without a migration fails offline.

They live in `app/domain/` for the same reason `ConversationState` does: the ORM
models and the services both need them, and neither may depend on the other. A
domain enum imports nothing.

**Three of these share value names and none is derived from another** (ADR-006,
ADR-007, closing C7). `APPROVED` is an `ApprovalStatus` and a `ConversationState`.
`PAYMENT_CONFIRMED` is an `OrderStatus` and a `ConversationState`. They are
different facts about different rows:

* `sessions.conversation_state` is what the UI renders. It authorizes nothing.
* `approvals.status` is the authorization artefact. Only this one can permit an
  order to exist.
* `orders.status` is where the money got to.

P§30 lists `CART`, `PENDING_APPROVAL`, `APPROVED` and `POLICY_VALIDATED` in what
reads like one order lifecycle. Those describe states in which **no order row
exists yet**, so they are cart, approval and policy states and they live there.
`OrderStatus` begins where an order does.
"""

from __future__ import annotations

from enum import StrEnum

__all__ = [
    "APPROVAL_STATUSES",
    "AUDIT_ACTORS",
    "AUDIT_EVENT_TYPES",
    "CART_STATUSES",
    "IDEMPOTENCY_SCOPES",
    "IDEMPOTENCY_STATUSES",
    "ORDER_STATUSES",
    "PAYMENT_STATUSES",
    "WEBHOOK_STATUSES",
    "ApprovalStatus",
    "AuditActor",
    "AuditEventType",
    "CartStatus",
    "IdempotencyScope",
    "IdempotencyStatus",
    "OrderStatus",
    "PaymentStatus",
    "WebhookStatus",
]


class CartStatus(StrEnum):
    """Where a cart is in its own short life."""

    ACTIVE = "ACTIVE"
    ORDERED = "ORDERED"
    ABANDONED = "ABANDONED"


class ApprovalStatus(StrEnum):
    """The authorization artefact's lifecycle (ADR-007).

    `PENDING` is what `request_approval` may write. `APPROVED` is what only a
    buyer action through `POST /api/cart/approve` may write, and the service
    method the tool calls has no parameter that could produce it.

    `SUPERSEDED` exists because a price change in **either** direction
    invalidates an approval (ADR-014): the old row stays readable for audit and
    points at the one that replaced it, rather than being mutated into agreement
    with a total the buyer never saw.
    """

    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"
    SUPERSEDED = "SUPERSEDED"


class IdempotencyScope(StrEnum):
    """What a key protects (ADR-013). One scope for now, named rather than assumed."""

    ORDER_CREATION = "ORDER_CREATION"


class IdempotencyStatus(StrEnum):
    """`RESERVED` is taken *before* the work starts, which is what makes the key
    a mutex rather than a receipt."""

    RESERVED = "RESERVED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class OrderStatus(StrEnum):
    """Where the money got to (ADR-006, ADR-011, ADR-012).

    Begins at `ORDER_CREATED`, because that is when a row first exists. The
    internal order is committed **before** Razorpay is called (ADR-011), so
    `ORDER_CREATED` and `RAZORPAY_ORDER_CREATED` are genuinely different states
    and the gap between them is recoverable rather than lost.

    `PAYMENT_CONFIRMED` is written only by verified webhook processing
    (ADR-012). Nothing a buyer or the agent says can produce it.
    """

    ORDER_CREATED = "ORDER_CREATED"
    RAZORPAY_ORDER_CREATED = "RAZORPAY_ORDER_CREATED"
    PAYMENT_PENDING = "PAYMENT_PENDING"
    PAYMENT_CONFIRMED = "PAYMENT_CONFIRMED"
    PAYMENT_FAILED = "PAYMENT_FAILED"
    ORDER_FAILED = "ORDER_FAILED"
    CANCELLED = "CANCELLED"


class PaymentStatus(StrEnum):
    """As reported by the provider, written only from a verified webhook."""

    CREATED = "CREATED"
    AUTHORIZED = "AUTHORIZED"
    CAPTURED = "CAPTURED"
    FAILED = "FAILED"
    REFUNDED = "REFUNDED"


class WebhookStatus(StrEnum):
    """What became of one delivery.

    `IGNORED` is not a failure: an event for an order this system does not know,
    or a duplicate the unique constraint caught, is correctly ignored and the
    record of having ignored it is the point.
    """

    RECEIVED = "RECEIVED"
    PROCESSED = "PROCESSED"
    IGNORED = "IGNORED"
    FAILED = "FAILED"


class AuditActor(StrEnum):
    """Who caused an event. `AGENT` and `USER` are never conflated: the whole
    architecture rests on the difference between what the model proposed and
    what the buyer authorized."""

    USER = "USER"
    AGENT = "AGENT"
    SYSTEM = "SYSTEM"
    RAZORPAY = "RAZORPAY"


class AuditEventType(StrEnum):
    """The audit vocabulary (ADR-006, closing E7).

    The first twelve are the ones RZP-07 names and are mandatory. The last four
    are added because the failure paths would otherwise be unreconstructable —
    an approval that vanished because it was superseded, and a webhook that was
    rejected or ignored, are exactly the events someone reads the audit log to
    understand.
    """

    # RZP-07's twelve
    CART_CREATED = "CART_CREATED"
    USER_APPROVED = "USER_APPROVED"
    POLICY_PASS = "POLICY_PASS"
    POLICY_FAIL = "POLICY_FAIL"
    ORDER_CREATED = "ORDER_CREATED"
    RAZORPAY_ORDER_CREATED = "RAZORPAY_ORDER_CREATED"
    CHECKOUT_STARTED = "CHECKOUT_STARTED"
    PAYMENT_WEBHOOK_RECEIVED = "PAYMENT_WEBHOOK_RECEIVED"
    PAYMENT_CONFIRMED = "PAYMENT_CONFIRMED"
    PAYMENT_FAILED = "PAYMENT_FAILED"
    PRICE_CHANGED = "PRICE_CHANGED"
    INVENTORY_FAILURE = "INVENTORY_FAILURE"

    # Four the failure paths need
    APPROVAL_SUPERSEDED = "APPROVAL_SUPERSEDED"
    APPROVAL_EXPIRED = "APPROVAL_EXPIRED"
    WEBHOOK_SIGNATURE_REJECTED = "WEBHOOK_SIGNATURE_REJECTED"
    WEBHOOK_DUPLICATE_IGNORED = "WEBHOOK_DUPLICATE_IGNORED"


def _values(enum: type[StrEnum]) -> tuple[str, ...]:
    return tuple(member.value for member in enum)


#: The tuples migration `0004` renders into `CHECK` constraints. Kept beside the
#: enums so a new member reaches the database in the same edit, and asserted
#: against the rendered DDL by `tests/db/test_migrations.py`.
CART_STATUSES = _values(CartStatus)
APPROVAL_STATUSES = _values(ApprovalStatus)
IDEMPOTENCY_SCOPES = _values(IdempotencyScope)
IDEMPOTENCY_STATUSES = _values(IdempotencyStatus)
ORDER_STATUSES = _values(OrderStatus)
PAYMENT_STATUSES = _values(PaymentStatus)
WEBHOOK_STATUSES = _values(WebhookStatus)
AUDIT_ACTORS = _values(AuditActor)
AUDIT_EVENT_TYPES = _values(AuditEventType)
