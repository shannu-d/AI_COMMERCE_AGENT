"""``approvals`` — the authorization artefact (ADR-006, ADR-007, P§10).

`architecture.md` requires this table and never defines it. It is the row the
whole architecture turns on: **an order cannot exist without one**, enforced by
`orders.approval_id NOT NULL` rather than by a check anyone can forget.

Three columns do the load-bearing work, and each answers "approved *what*,
exactly?":

* `cart_version` — the version that was approved, not the current one. A cart
  that changed after approval has a version the approval does not match, and the
  mismatch is what makes staleness detectable rather than assumed.
* `approved_total` — the number the buyer actually saw. A price change in
  **either** direction invalidates the approval (ADR-014): a cheaper cart is
  still not the cart they agreed to.
* `items_fingerprint` — SHA-256 over the canonical item tuples. Version and total
  can both match while the composition differs — swap one item for another at the
  same price — and the fingerprint is what closes that.

Nothing here derives from `sessions.conversation_state`. A session displaying
`APPROVED` authorizes nothing; only a row in this table with `status =
'APPROVED'` does (ADR-007, closing C7).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import (
    CHAR,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, CurrencyCode, Money, uuid_pk
from app.db.models._enums import in_list
from app.domain.commerce import APPROVAL_STATUSES, ApprovalStatus

if TYPE_CHECKING:
    from app.db.models.cart import Cart
    from app.db.models.session import Session


class Approval(Base):
    """One buyer authorization of one exact cart version and total."""

    __tablename__ = "approvals"
    __table_args__ = (
        CheckConstraint(in_list("status", APPROVAL_STATUSES), name="status_is_known"),
        CheckConstraint("approved_total >= 0", name="approved_total_is_not_negative"),
        CheckConstraint("cart_version >= 1", name="cart_version_starts_at_one"),
        # An APPROVED row without a timestamp would be an authorization nobody
        # can date, which is the one thing an audit of a money path must have.
        CheckConstraint(
            "status <> 'APPROVED' OR approved_at IS NOT NULL",
            name="approved_rows_carry_a_timestamp",
        ),
        # A given cart version can be approved at most once. Partial, because the
        # same cart accumulates SUPERSEDED and EXPIRED rows and only the live
        # approval is exclusive — the history is the point (ADR-014).
        Index(
            "uq_approvals_cart_id_cart_version_approved",
            "cart_id",
            "cart_version",
            unique=True,
            postgresql_where=text("status = 'APPROVED'"),
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    session_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("sessions.id"), nullable=False
    )
    cart_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("carts.id"), nullable=False
    )
    cart_version: Mapped[int] = mapped_column(Integer, nullable=False)
    approved_total: Mapped[Decimal] = mapped_column(Money, nullable=False)
    currency: Mapped[str] = mapped_column(CurrencyCode, nullable=False)
    #: SHA-256 hex. Fixed width, so a truncated or differently-encoded digest is
    #: rejected by the column rather than compared as unequal forever.
    items_fingerprint: Mapped[str] = mapped_column(CHAR(64), nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default=text(f"'{ApprovalStatus.PENDING.value}'")
    )
    #: Points forward to the approval that replaced this one, so a superseded
    #: row stays readable and the chain is walkable during an audit.
    superseded_by_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("approvals.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    session: Mapped[Session] = relationship()
    cart: Mapped[Cart] = relationship()
    superseded_by: Mapped[Approval | None] = relationship(remote_side="Approval.id")

    def __repr__(self) -> str:
        return f"<Approval {self.id} cart={self.cart_id} v{self.cart_version} {self.status}>"
