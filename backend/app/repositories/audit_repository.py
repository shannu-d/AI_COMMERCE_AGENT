"""The audit log's only writer (M13; ADR-006, A§40, RZP-07).

**This repository exposes `append` and reads. It has no update and no delete, and
that absence is the design.** ADR-006 states the rule: the table is append-only,
there is no `updated_at`, and in a deployed environment the application's
database role is granted `INSERT` and `SELECT` on it and nothing else. A method
that could rewrite history would make the log evidence of nothing.

`seq` gives a total order, because timestamps tie: several events written in one
transaction can share a microsecond, and *what happened next* is the question an
audit exists to answer.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import AuditEvent
from app.domain.commerce import AuditActor, AuditEventType

__all__ = ["AuditRepository"]


class AuditRepository:
    """Appends to `audit_events`, and reads them back in order."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def append(
        self,
        event_type: AuditEventType,
        actor: AuditActor,
        *,
        session_id: uuid.UUID | None = None,
        cart_id: uuid.UUID | None = None,
        order_id: uuid.UUID | None = None,
        payment_id: uuid.UUID | None = None,
        payload: dict[str, Any] | None = None,
    ) -> AuditEvent:
        """Write one fact. The only mutation this class permits.

        Typed on the enums rather than on strings, so an event type nobody
        defined cannot be appended and then discovered later by whoever tries to
        read the log.
        """
        event = AuditEvent(
            event_type=event_type.value,
            actor=actor.value,
            session_id=session_id,
            cart_id=cart_id,
            order_id=order_id,
            payment_id=payment_id,
            payload=payload or {},
        )
        self._session.add(event)
        self._session.flush()
        return event

    # -- reads ---------------------------------------------------------------

    def for_session(self, session_id: uuid.UUID) -> Sequence[AuditEvent]:
        return self._ordered(AuditEvent.session_id == session_id)

    def for_order(self, order_id: uuid.UUID) -> Sequence[AuditEvent]:
        return self._ordered(AuditEvent.order_id == order_id)

    def for_cart(self, cart_id: uuid.UUID) -> Sequence[AuditEvent]:
        return self._ordered(AuditEvent.cart_id == cart_id)

    def _ordered(self, *criteria) -> Sequence[AuditEvent]:
        """Always by `seq`, never by `created_at`.

        Two events in one transaction can share a timestamp, and an audit read
        back in an ambiguous order is an audit that cannot answer the question
        it exists for.
        """
        return list(
            self._session.execute(
                select(AuditEvent).where(*criteria).order_by(AuditEvent.seq)
            ).scalars()
        )
