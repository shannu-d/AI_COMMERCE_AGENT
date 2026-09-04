"""``merchant_activity`` — an append-only record of dashboard writes (ADR-023 §7).

Why a second log rather than a wider `audit_events`: see
`app/domain/activity.py`. In short, `audit_events` reconstructs one
*transaction* and hangs off a session, cart, order or payment; a price edit has
none of those and would arrive as four null columns and two widened `CHECK`s,
leaving one table answering two unrelated questions.

**Append-only by convention and by shape.** There is no `updated_at` and nothing
in the application updates or deletes a row. `seq` gives a total order, because
two edits inside one transaction share a timestamp and "what happened next" is
the question a log is read to answer.

**The actor survives the account.** `actor_user_id` is `ON DELETE SET NULL` and
`actor_email` is copied in at write time, so removing an administrator does not
quietly rewrite the history of what they changed.

**`payload` carries the before and after, and never a secret.** It exists so the
answer to "what did this change" does not depend on the row still existing, or
on it not having been changed again since.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, uuid_pk
from app.db.models._enums import in_list
from app.domain.activity import MERCHANT_ACTIONS, MERCHANT_ENTITY_TYPES


class MerchantActivity(Base):
    """One thing an administrator did to a merchant's catalogue."""

    __tablename__ = "merchant_activity"
    __table_args__ = (
        UniqueConstraint("seq"),
        CheckConstraint(in_list("action", MERCHANT_ACTIONS), name="action_is_known"),
        CheckConstraint(in_list("entity_type", MERCHANT_ENTITY_TYPES), name="entity_type_is_known"),
        CheckConstraint("jsonb_typeof(payload) = 'object'", name="payload_is_an_object"),
        # The dashboard reads one merchant's log newest-first, and that is the
        # only way it is ever read.
        Index("ix_merchant_activity_merchant_seq", "merchant_id", "seq"),
        Index("ix_merchant_activity_actor", "actor_user_id"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    #: A total order across the whole log. Timestamps tie within a transaction.
    seq: Mapped[int] = mapped_column(BigInteger, Identity(always=False), nullable=False)
    merchant_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("merchants.id", ondelete="CASCADE"), nullable=False
    )
    #: Null only once the administrator's account is gone; `actor_email` keeps
    #: the history readable after that.
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    actor_email: Mapped[str] = mapped_column(String(320), nullable=False)
    action: Mapped[str] = mapped_column(String(48), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(32), nullable=False)
    #: No foreign key: a product may later be deleted, and the log of its
    #: creation must outlive it.
    entity_id: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    #: A short human-readable subject, e.g. a SKU or a product name, so the log
    #: is legible without a join to a row that may no longer exist.
    subject: Mapped[str | None] = mapped_column(String(200), nullable=True)
    #: Before-and-after of what changed. Never contains a secret (L§45).
    payload: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<MerchantActivity {self.seq} {self.action} {self.subject!r}>"


__all__ = ["MerchantActivity"]
