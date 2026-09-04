"""Recording and reading merchant activity (ADR-023 §7).

**The only writer of `merchant_activity`.** One place means the rules — the
actor is the authenticated administrator, the merchant is theirs, the payload
carries no secret — can only be wrong once.

Two things this service refuses to do:

*It never invents an actor.* `record` takes an `AuthenticatedUser`, not an id or
an email, so there is no call site that can log an action against somebody who
did not perform it. A route that has no authenticated merchant cannot write a
row at all.

*It never widens a scope.* Reading takes the merchant id the route resolved from
the token, and there is no parameter for another one.

Recording is `flush`, never `commit`. The row belongs to the same unit of work
as the change it describes: if the edit rolls back, so does the record of it,
and a log full of edits that never happened would be worse than no log.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session as DbSession

from app.db.models import MerchantActivity
from app.domain.activity import MerchantAction, MerchantEntityType
from app.domain.identity import AuthenticatedUser

logger = logging.getLogger(__name__)

__all__ = ["ActivityService", "ActivityView"]


@dataclass(frozen=True, slots=True)
class ActivityView:
    """One logged action, as a reader sees it."""

    id: uuid.UUID
    seq: int
    action: str
    entity_type: str
    entity_id: uuid.UUID | None
    subject: str | None
    actor_email: str
    payload: dict[str, Any]
    created_at: datetime


def _to_view(row: MerchantActivity) -> ActivityView:
    return ActivityView(
        id=row.id,
        seq=row.seq,
        action=row.action,
        entity_type=row.entity_type,
        entity_id=row.entity_id,
        subject=row.subject,
        actor_email=row.actor_email,
        payload=dict(row.payload or {}),
        created_at=row.created_at,
    )


class ActivityService:
    """Append to, and read, one merchant's activity log."""

    def __init__(self, session: DbSession) -> None:
        self._session = session

    def record(
        self,
        actor: AuthenticatedUser,
        action: MerchantAction,
        entity_type: MerchantEntityType,
        *,
        entity_id: uuid.UUID | None = None,
        subject: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> None:
        """Append one row, in the caller's transaction.

        The merchant is `actor.merchant_id` and cannot be passed in: an
        administrator can only ever be recorded as acting on their own
        catalogue, which is the same guarantee the dashboard routes rest on.
        """
        if actor.merchant_id is None:
            # Unreachable through the routes — `require_merchant` has already
            # established this — but an assertion here would be a crash in a
            # logging path, and losing a log entry is better than losing an edit.
            logger.warning("activity not recorded: actor has no merchant")
            return

        self._session.add(
            MerchantActivity(
                id=uuid.uuid4(),
                merchant_id=actor.merchant_id,
                actor_user_id=actor.id,
                # Copied rather than joined, so the log stays readable after an
                # administrator's account is removed.
                actor_email=actor.email,
                action=action.value,
                entity_type=entity_type.value,
                entity_id=entity_id,
                subject=(subject[:200] if isinstance(subject, str) else None),
                payload=dict(payload or {}),
            )
        )
        # Flush, not commit: this row lives or dies with the change it describes.
        self._session.flush()

    def list_for_merchant(
        self,
        merchant_id: uuid.UUID,
        *,
        action: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[ActivityView], int]:
        """A page of the log, newest first, with a total count."""
        limit = max(1, min(limit, 200))
        offset = max(0, offset)
        where = [MerchantActivity.merchant_id == merchant_id]
        if action is not None:
            where.append(MerchantActivity.action == action.upper())

        total = int(
            self._session.execute(
                select(func.count()).select_from(MerchantActivity).where(*where)
            ).scalar_one()
        )
        rows = (
            self._session.execute(
                select(MerchantActivity)
                .where(*where)
                .order_by(MerchantActivity.seq.desc())
                .offset(offset)
                .limit(limit)
            )
            .scalars()
            .all()
        )
        return [_to_view(row) for row in rows], total
