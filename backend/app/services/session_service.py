"""Conversation persistence (A§37, A§38, ADR-006, closes C3).

A deterministic service like the others: it takes a `Session`, scopes every read
by merchant (ADR-002), and returns frozen domain values rather than ORM rows. It
imports nothing from `app.llm` or `app.agent` — the runtime passes it validated
data, and this module has no opinion about where that data came from.

What it stores is conversation state, never authorization. A session sitting in
`APPROVED` authorizes nothing; only an `approvals` row does (ADR-007). The
methods here have no parameter through which an approval could be written,
because the table does not exist yet and, when it does, it will not be reachable
from this class.

`intent` is the accumulated `BuyerIntent` A§37 requires to survive across turns.
It is stored as the JSON the model produced *after* validation, so a later turn
merges against something that already passed a schema rather than against raw
text.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session as DbSession

from app.db.models.session import Session as SessionRow
from app.db.models.session import SessionMessage
from app.domain.conversation import ConversationState

logger = logging.getLogger(__name__)

__all__ = ["SessionService", "SessionView"]


class SessionView:
    """A conversation, detached from the database row that produced it.

    Deliberately not a frozen dataclass: `intent` is a mutable mapping the
    runtime merges into across a turn, and copying it on every read would hide
    which layer owns the accumulation.
    """

    __slots__ = ("conversation_state", "id", "intent", "merchant_id")

    def __init__(
        self,
        *,
        id: uuid.UUID,
        merchant_id: uuid.UUID,
        conversation_state: ConversationState,
        intent: dict[str, Any],
    ) -> None:
        self.id = id
        self.merchant_id = merchant_id
        self.conversation_state = conversation_state
        self.intent = intent

    def __repr__(self) -> str:
        return f"<SessionView {self.id} state={self.conversation_state.value}>"


def _to_view(row: SessionRow) -> SessionView:
    return SessionView(
        id=row.id,
        merchant_id=row.merchant_id,
        conversation_state=ConversationState(row.conversation_state),
        intent=dict(row.intent or {}),
    )


class SessionService:
    """Reads and writes `sessions` and `session_messages`."""

    def __init__(self, session: DbSession) -> None:
        self._session = session

    # -- lifecycle -----------------------------------------------------------

    def create(self, merchant_id: uuid.UUID) -> SessionView:
        """A new conversation. The `session_id` is server-minted (ADR-010)."""
        row = SessionRow(
            merchant_id=merchant_id,
            conversation_state=ConversationState.NEW_SESSION.value,
            intent={},
        )
        self._session.add(row)
        self._session.flush()
        logger.info("session created", extra={"session_id": str(row.id)})
        return _to_view(row)

    def get(self, merchant_id: uuid.UUID, session_id: uuid.UUID) -> SessionView | None:
        """`None` for an unknown id — the caller turns that into SESSION_NOT_FOUND.

        Merchant-scoped, so one merchant's session id is not a key to another's
        conversation even if it were guessed correctly.
        """
        row = self._row(merchant_id, session_id)
        return None if row is None else _to_view(row)

    def _row(self, merchant_id: uuid.UUID, session_id: uuid.UUID) -> SessionRow | None:
        return self._session.execute(
            select(SessionRow).where(
                SessionRow.id == session_id,
                SessionRow.merchant_id == merchant_id,
            )
        ).scalar_one_or_none()

    # -- mutation ------------------------------------------------------------

    def touch(self, merchant_id: uuid.UUID, session_id: uuid.UUID) -> None:
        """Record that the buyer is present.

        Separate from any state change: a turn that alters nothing still proves
        presence, and expiry is a question about presence.
        """
        row = self._row(merchant_id, session_id)
        if row is not None:
            row.last_seen_at = func.now()

    def set_state(
        self,
        merchant_id: uuid.UUID,
        session_id: uuid.UUID,
        state: ConversationState,
    ) -> None:
        """Move the display state (A§25, ADR-010).

        Takes a `ConversationState` rather than a string, so a value outside the
        enum cannot reach the column's CHECK constraint to be rejected there.
        """
        row = self._row(merchant_id, session_id)
        if row is None:
            return
        row.conversation_state = state.value

    def set_intent(
        self,
        merchant_id: uuid.UUID,
        session_id: uuid.UUID,
        intent: dict[str, Any],
    ) -> None:
        """Replace the accumulated intent (A§37).

        Replace rather than merge: the merge is `app.llm.extractor.merge_intent`,
        which knows the difference between a field the model omitted and one it
        cleared. Doing it again here, with a different rule, is how two layers
        come to disagree about what the buyer asked for.
        """
        row = self._row(merchant_id, session_id)
        if row is None:
            return
        row.intent = dict(intent)

    # -- history -------------------------------------------------------------

    def append_message(
        self,
        merchant_id: uuid.UUID,
        session_id: uuid.UUID,
        *,
        role: str,
        content: str | None = None,
        tool_payload: dict[str, Any] | None = None,
    ) -> None:
        """Append one turn of history (A§38).

        The sequence is computed from the rows that exist, and the table's
        `UNIQUE(session_id, sequence)` is what actually enforces monotonicity —
        a concurrent append fails loudly rather than overwriting.

        L§45: nothing containing a secret is ever passed here. The client refuses
        to *send* a prompt carrying one; this refuses to be the place one is
        written down.
        """
        if content is None and tool_payload is None:
            raise ValueError("a session message carries content, a payload, or both")
        if self._row(merchant_id, session_id) is None:
            raise LookupError(f"session {session_id} does not exist for this merchant")

        next_sequence = (
            self._session.execute(
                select(func.coalesce(func.max(SessionMessage.sequence), -1)).where(
                    SessionMessage.session_id == session_id
                )
            ).scalar_one()
            + 1
        )
        self._session.add(
            SessionMessage(
                session_id=session_id,
                sequence=next_sequence,
                role=role,
                content=content,
                tool_payload=tool_payload,
            )
        )
        self._session.flush()

    def history(
        self,
        merchant_id: uuid.UUID,
        session_id: uuid.UUID,
        *,
        limit: int | None = None,
        roles: tuple[str, ...] = ("user", "assistant"),
    ) -> list[SessionMessage]:
        """The most recent `limit` messages, oldest first.

        `tool` rows are excluded by default. A§50 says tool results may be
        retained *during* a turn; replaying every one of them into the next
        turn's prompt is how a context window fills with data the structured
        intent already carries (L§27).
        """
        if self._row(merchant_id, session_id) is None:
            return []

        statement = (
            select(SessionMessage)
            .where(
                SessionMessage.session_id == session_id,
                SessionMessage.role.in_(roles),
            )
            .order_by(SessionMessage.sequence.desc())
        )
        if limit is not None:
            statement = statement.limit(limit)

        rows = list(self._session.execute(statement).scalars())
        rows.reverse()
        return rows
