"""The Approval Service (M8; ADR-007, P§9, P§10, A§26, A§27).

This module holds the one record in the system that says *a human authorized a
payment*, and its whole design is about who is allowed to write it.

**Only a buyer action writes `APPROVED`.** `request()` writes `PENDING` and has
no parameter through which any other status could arrive; `approve()` is the
only method that writes `APPROVED`, and only `POST /api/cart/approve` calls it.
P§9 draws the line this enforces: "Show me the cart" is not approval, and
neither is "How much is it?". Putting the authorization signal inside the
probabilistic component would make "yeah I was just asking" indistinguishable
from "yes, buy it".

**An approval binds to five things**, all recorded on the row: session, cart,
cart version, approved total with currency, and the items fingerprint. The
fingerprint is there because a total is not a composition — two different carts
can reach the same total, and the version catches that only while versions are
never reused.

**Invalidation is immediate and unconditional**, performed by the same code path
that makes the change rather than by a sweeper. A price change in *either*
direction supersedes: the buyer approved a specific total, and charging a
different one — cheaper or not — is charging an amount that was never
authorized.

**This service authorizes nothing by itself.** An approval that passes every
check here can still fail policy, because the Policy Engine re-reads prices and
stock while an approval only remembers them (ADR-011, ADR-014).

Audit events are M13. ADR-007 calls for an `APPROVAL_SUPERSEDED` event on every
supersession; `audit_events` exists from M6 and the Audit Service does not, so
the supersede path is written to be the single place that emission will hook
into, and the event is not yet written. That is a recorded gap, not an oversight.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from app.db.models import Approval, IdempotencyKey
from app.domain.approval import ApprovalFailure, ApprovalView, items_fingerprint, lines_from
from app.domain.cart import CartView
from app.domain.commerce import ApprovalStatus, IdempotencyScope, IdempotencyStatus
from app.services.audit_service import AuditService

logger = logging.getLogger(__name__)

__all__ = ["IDEMPOTENCY_TTL_SECONDS", "ApprovalError", "ApprovalService"]

#: 24 hours (ADR-013, closing D4). Comfortably longer than the 15-minute
#: approval TTL, so a key always outlives the approval it protects and a late
#: duplicate submission finds a stored result rather than a clean slate.
IDEMPOTENCY_TTL_SECONDS = 24 * 60 * 60


class ApprovalError(Exception):
    """An approval that cannot be created or cannot be used."""

    def __init__(self, failure: ApprovalFailure, message: str, *, details: dict | None = None):
        self.failure = failure
        self.message = message
        self.details = details or {}
        super().__init__(f"{failure.value}: {message}")


def _to_view(row: Approval) -> ApprovalView:
    return ApprovalView(
        id=row.id,
        session_id=row.session_id,
        cart_id=row.cart_id,
        cart_version=row.cart_version,
        approved_total=row.approved_total,
        currency=row.currency,
        items_fingerprint=row.items_fingerprint,
        status=ApprovalStatus(row.status),
        created_at=row.created_at,
        approved_at=row.approved_at,
        expires_at=row.expires_at,
        superseded_by_id=row.superseded_by_id,
    )


class ApprovalService:
    """Writes and reads `approvals`. Nothing else may write that table."""

    def __init__(self, session: DbSession, *, ttl_seconds: int = 900) -> None:
        self._session = session
        self._ttl = timedelta(seconds=ttl_seconds)
        self._audit = AuditService(session)

    # -- the agent's half: asking ------------------------------------------

    def request(self, session_id: uuid.UUID, cart: CartView) -> ApprovalView:
        """Record that approval has been *asked for*. Writes `PENDING` only.

        This is what `request_approval()` calls. There is deliberately no
        `status` parameter: the method cannot be persuaded, mis-called or
        refactored into writing `APPROVED`, because the value is a literal in
        one line of this method's body (ADR-007, closing D5).

        A `PENDING` row authorizes nothing. It records that the agent asked and
        the buyer has not yet answered.
        """
        if cart.is_empty:
            raise ApprovalError(ApprovalFailure.CART_EMPTY, "there is nothing in the cart")

        row = Approval(
            session_id=session_id,
            cart_id=cart.id,
            cart_version=cart.version,
            approved_total=cart.total,
            currency=cart.currency,
            items_fingerprint=items_fingerprint(lines_from(cart.items)),
            status=ApprovalStatus.PENDING.value,
            expires_at=self._now() + self._ttl,
        )
        self._session.add(row)
        self._session.flush()
        logger.info(
            "approval requested",
            extra={"approval_id": str(row.id), "cart_id": str(cart.id)},
        )
        return _to_view(row)

    # -- the buyer's half: answering ---------------------------------------

    def approve(
        self,
        session_id: uuid.UUID,
        cart: CartView,
        *,
        cart_version: int,
        expected_total: Decimal | None = None,
    ) -> ApprovalView:
        """Record a buyer's authorization of one exact cart state.

        Callable only from `POST /api/cart/approve`. `cart_version` is what the
        buyer's screen was showing, not what the cart is now: submitting it is
        how a stale view becomes *detectable* rather than silently applied to
        whatever the cart has since become (A§26, A§27).

        `expected_total` is optional and checked when supplied. It is the second
        half of the same idea — a client that renders a total should be able to
        say which one it rendered.
        """
        if cart.is_empty:
            raise ApprovalError(ApprovalFailure.CART_EMPTY, "there is nothing to approve")

        if cart_version != cart.version:
            raise ApprovalError(
                ApprovalFailure.CART_VERSION_STALE,
                "the cart changed since you last saw it; please review it again",
                details={"approved_version": cart_version, "current_version": cart.version},
            )
        if expected_total is not None and expected_total != cart.total:
            raise ApprovalError(
                ApprovalFailure.TOTAL_CHANGED,
                "the total changed since you last saw it; please review it again",
                details={"expected_total": str(expected_total), "current_total": str(cart.total)},
            )

        # A fresh approval supersedes any earlier one for this cart (ADR-007
        # invalidation rule 4). Done before the insert, or the partial unique
        # index on (cart_id, cart_version) WHERE status = 'APPROVED' would refuse
        # the new row rather than the old one giving way.
        self.supersede_for_cart(cart.id, reason="a fresh approval replaced it")

        now = self._now()
        row = Approval(
            session_id=session_id,
            cart_id=cart.id,
            cart_version=cart.version,
            approved_total=cart.total,
            currency=cart.currency,
            items_fingerprint=items_fingerprint(lines_from(cart.items)),
            status=ApprovalStatus.APPROVED.value,
            approved_at=now,
            expires_at=now + self._ttl,
        )
        self._session.add(row)
        self._session.flush()

        # ADR-013: the backend mints the idempotency key here, in the same
        # transaction, bound to this approval's exact state. Minted by the
        # backend rather than chosen by the client because the key must be
        # *derived from the state it protects* - a client-chosen one protects
        # only against that client's own retries and could be reused across
        # genuinely different carts.
        #
        # A cart mutation bumps the version and supersedes this approval, so the
        # next approval mints a new key. That is P§16's "fresh idempotency key",
        # obtained as a consequence of the approval rules rather than as a
        # separate mechanism anyone has to remember.
        self._session.add(
            IdempotencyKey(
                key=str(uuid.uuid4()),
                scope=IdempotencyScope.ORDER_CREATION.value,
                session_id=session_id,
                cart_id=cart.id,
                cart_version=cart.version,
                approved_total=cart.total,
                currency=cart.currency,
                expires_at=now + timedelta(seconds=IDEMPOTENCY_TTL_SECONDS),
            )
        )
        self._session.flush()

        self._audit.user_approved(
            session_id,
            cart.id,
            approval_id=row.id,
            cart_version=cart.version,
            approved_total=cart.total,
            currency=cart.currency,
        )
        logger.info(
            "cart approved by user",
            extra={
                "approval_id": str(row.id),
                "cart_id": str(cart.id),
                "cart_version": cart.version,
            },
        )
        return _to_view(row)

    def reject(self, cart_id: uuid.UUID) -> None:
        """The buyer declined. Terminal, and every pending ask goes with it."""
        for row in self._live_rows(cart_id, ApprovalStatus.PENDING):
            row.status = ApprovalStatus.REJECTED.value
        self._session.flush()

    # -- invalidation ------------------------------------------------------

    def supersede_for_cart(self, cart_id: uuid.UUID, *, reason: str) -> int:
        """Supersede every live approval for a cart. Returns how many.

        Called by `CartService` on **every** mutation and by every refresh that
        finds a changed price — including a price *decrease* (ADR-007
        invalidation rule 2, closing D2). Being called from the code path that
        makes the change is what makes invalidation immediate rather than
        eventual: there is no window in which a changed cart still has a valid
        approval.

        M13 will emit an `APPROVAL_SUPERSEDED` audit event from here. The Audit
        Service does not exist yet; this is the one place it will hook into.
        """
        rows = [
            *self._live_rows(cart_id, ApprovalStatus.APPROVED),
            *self._live_rows(cart_id, ApprovalStatus.PENDING),
        ]
        for row in rows:
            row.status = ApprovalStatus.SUPERSEDED.value
            # M13 closes the gap ADR-007 opened and M8 recorded: without this
            # row, an approval that vanished between two reads is
            # unexplainable - and the price-drift scenario is precisely a story
            # about an approval vanishing.
            self._audit.approval_superseded(cart_id, approval_id=row.id, reason=reason)
        if rows:
            self._session.flush()
            logger.info(
                "approvals superseded",
                extra={"cart_id": str(cart_id), "count": len(rows), "reason": reason},
            )
        return len(rows)

    def expire_stale(self, cart_id: uuid.UUID) -> int:
        """Mark elapsed approvals `EXPIRED`.

        An optimization, never the mechanism. `ApprovalView.authorizes` refuses
        an elapsed row whether or not this ever ran, because an approval that
        expired while nobody was looking must still be refused when it is used.
        """
        now = self._now()
        rows = [
            row
            for row in self._live_rows(cart_id, ApprovalStatus.APPROVED)
            if row.expires_at <= now
        ]
        for row in rows:
            row.status = ApprovalStatus.EXPIRED.value
            self._audit.approval_expired(cart_id, approval_id=row.id)
        if rows:
            self._session.flush()
        return len(rows)

    # -- reads -------------------------------------------------------------

    def current(self, cart_id: uuid.UUID) -> ApprovalView | None:
        """The live `APPROVED` row for a cart, if there is one.

        At most one can exist: a partial unique index enforces one approval per
        cart version, and every earlier one is superseded before a new one is
        written.
        """
        rows = self._live_rows(cart_id, ApprovalStatus.APPROVED)
        return _to_view(rows[0]) if rows else None

    def get(self, approval_id: uuid.UUID) -> ApprovalView | None:
        row = self._session.get(Approval, approval_id)
        return None if row is None else _to_view(row)

    def history(self, cart_id: uuid.UUID) -> list[ApprovalView]:
        """Every approval ever written for a cart, oldest first.

        ADR-014's price-drift recovery reads this: a superseded approval stays
        readable so "you approved ₹1,499 and it is now ₹1,799" is a statement
        about a record rather than about a memory.
        """
        rows = self._session.execute(
            select(Approval).where(Approval.cart_id == cart_id).order_by(Approval.created_at)
        ).scalars()
        return [_to_view(row) for row in rows]

    def validate_against(self, approval: ApprovalView, cart: CartView) -> None:
        """Raise unless this approval still describes this cart.

        The check the Policy Engine will run before an order exists (M9). Kept
        here so the writer and the validator share one notion of "still matches",
        and so the fingerprint is computed by one function on both sides.
        """
        now = self._now()
        if approval.status is not ApprovalStatus.APPROVED:
            raise ApprovalError(ApprovalFailure.NOT_APPROVED, "this cart has not been approved")
        if approval.superseded_by_id is not None:
            raise ApprovalError(ApprovalFailure.SUPERSEDED, "that approval was replaced")
        if approval.is_expired_at(now):
            raise ApprovalError(
                ApprovalFailure.EXPIRED, "that approval has expired; please confirm again"
            )
        if approval.cart_version != cart.version:
            raise ApprovalError(
                ApprovalFailure.CART_VERSION_STALE,
                "the cart changed after it was approved",
                details={
                    "approved_version": approval.cart_version,
                    "current_version": cart.version,
                },
            )
        if approval.approved_total != cart.total:
            raise ApprovalError(
                ApprovalFailure.TOTAL_CHANGED,
                "the total changed after the cart was approved",
                details={
                    "approved_total": str(approval.approved_total),
                    "current_total": str(cart.total),
                },
            )
        if approval.items_fingerprint != items_fingerprint(lines_from(cart.items)):
            raise ApprovalError(
                ApprovalFailure.ITEMS_CHANGED,
                "the items changed after the cart was approved",
            )

    # -- internals ---------------------------------------------------------

    def _live_rows(self, cart_id: uuid.UUID, status: ApprovalStatus) -> list[Approval]:
        return list(
            self._session.execute(
                select(Approval)
                .where(Approval.cart_id == cart_id, Approval.status == status.value)
                .order_by(Approval.created_at.desc())
            ).scalars()
        )

    @staticmethod
    def _now() -> datetime:
        return datetime.now(UTC)

    def idempotency_key_for(self, cart_id: uuid.UUID, cart_version: int) -> str | None:
        """The key minted alongside the live approval for this cart version.

        Returned to the client with the approval, and presented back on
        `POST /api/orders`. `None` when no key was minted, which happens only
        for an approval recorded before this milestone.
        """
        row = (
            self._session.execute(
                select(IdempotencyKey)
                .where(
                    IdempotencyKey.cart_id == cart_id,
                    IdempotencyKey.cart_version == cart_version,
                    IdempotencyKey.status == IdempotencyStatus.RESERVED.value,
                )
                .order_by(IdempotencyKey.created_at.desc())
            )
            .scalars()
            .first()
        )
        return None if row is None else row.key
