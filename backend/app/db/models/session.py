"""``sessions`` and ``session_messages`` — ADR-006, A§37, A§38.

These two arrive with **M5** rather than with the rest of the commerce schema in
M6, and the reason is a decision that is already closed. Open question C3,
session and approval persistence, is closed by ADR-006 as *PostgreSQL*; the task
breakdown gives AGENT-01 — the M5 runtime skeleton — the job of closing it. A
runtime cannot close C3 with a dictionary. ADR-006 spells out the objection to
the alternative: in-memory session state would make the price-drift and
duplicate-request scenarios untestable across processes.

The other nine tables ADR-006 designs remain M6. Nothing here touches money, a
cart, an order or an approval, so the M5/M6 line still falls where D§36 and D§39
put it: this milestone reads the catalog and remembers the conversation, and it
writes no commerce record.

``sessions.intent`` holds the accumulated structured intent A§37 requires to
survive across turns. It is model *output* that has passed validation — a
``BuyerIntent``, never raw text — and it authorizes nothing on its own.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, uuid_pk
from app.domain.conversation import CONVERSATION_STATES, ConversationState

if TYPE_CHECKING:
    from app.db.models.merchant import Merchant

#: Who produced a message. ``tool`` rows carry ``tool_payload`` rather than
#: prose, which is what keeps a tool result auditable as structured data instead
#: of as a sentence someone has to parse back.
SESSION_MESSAGE_ROLES: tuple[str, ...] = ("user", "assistant", "tool")


def _in_list(column: str, values: tuple[str, ...]) -> str:
    rendered = ", ".join(f"'{value}'" for value in values)
    return f"{column} IN ({rendered})"


class Session(Base, TimestampMixin):
    """One buyer conversation. The ``session_id`` every API response carries."""

    __tablename__ = "sessions"
    __table_args__ = (
        CheckConstraint(
            _in_list("conversation_state", CONVERSATION_STATES),
            name="conversation_state_is_known",
        ),
        # A§37: the accumulated intent is an object, never a scalar or a list.
        # The same rule the catalog applies to every JSONB column.
        CheckConstraint("jsonb_typeof(intent) = 'object'", name="intent_is_an_object"),
        # Every read is "this session, for this merchant": ADR-002 injects the
        # merchant server-side on every call, so it is part of the lookup rather
        # than a filter applied afterwards.
        Index("ix_sessions_merchant_id", "merchant_id"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    merchant_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("merchants.id", ondelete="CASCADE"),
        nullable=False,
    )
    conversation_state: Mapped[str] = mapped_column(
        String(48),
        nullable=False,
        server_default=text(f"'{ConversationState.NEW_SESSION.value}'"),
    )
    intent: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    #: Separate from ``updated_at``: a turn that changes nothing still proves the
    #: buyer is present, and expiry is a question about presence rather than
    #: about mutation.
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    merchant: Mapped[Merchant] = relationship()
    messages: Mapped[list[SessionMessage]] = relationship(
        back_populates="session",
        cascade="all, delete-orphan",
        order_by="SessionMessage.sequence",
    )

    def __repr__(self) -> str:
        return f"<Session {self.id} state={self.conversation_state}>"


class SessionMessage(Base):
    """One turn of conversation history (A§38).

    A table rather than a growing JSONB column on ``sessions``: appending to an
    array means rewriting it, and an unbounded column has no natural place to
    put an index or a limit.

    L§45: no secret and no API key is ever written here.
    """

    __tablename__ = "session_messages"
    __table_args__ = (
        UniqueConstraint("session_id", "sequence"),
        CheckConstraint(_in_list("role", SESSION_MESSAGE_ROLES), name="role_is_known"),
        CheckConstraint("sequence >= 0", name="sequence_is_not_negative"),
        # A message is prose or a structured payload. A row with neither records
        # nothing, and the constraint says so rather than leaving it to callers.
        CheckConstraint(
            "content IS NOT NULL OR tool_payload IS NOT NULL",
            name="message_carries_content_or_payload",
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    session_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("sessions.id", ondelete="CASCADE"),
        nullable=False,
    )
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    content: Mapped[str | None] = mapped_column(Text, nullable=True)
    tool_payload: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    session: Mapped[Session] = relationship(back_populates="messages")

    def __repr__(self) -> str:
        return f"<SessionMessage {self.session_id}#{self.sequence} {self.role}>"
