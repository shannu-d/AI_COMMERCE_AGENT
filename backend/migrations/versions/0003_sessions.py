"""sessions and session_messages: conversation state (ADR-006, A§37, A§38).

A third migration rather than part of a future commerce one, for the same reason
``0002`` is separate from ``0001``: it keeps what each milestone added legible on
its own.

ADR-006 designs eleven tables and assigns them to M6. These two come forward to
M5 because open question C3 — session and approval persistence — is closed by
that ADR as *PostgreSQL*, and the task breakdown gives AGENT-01, the M5 runtime
skeleton, the job of closing it. A runtime cannot close C3 with a dictionary, and
ADR-006 states the objection to trying: in-memory session state would make the
price-drift and duplicate-request scenarios untestable across processes.

The nine remaining tables stay in M6. Nothing created here holds money, a cart,
an order or an approval, so the boundary D§36 and D§39 draw around the catalog
milestone is unmoved.

Revision ID: 0003
Revises: 0002
Created: 2026-09-01
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from app.db.models.session import SESSION_MESSAGE_ROLES
from app.domain.conversation import CONVERSATION_STATES

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _in_list(column: str, values: tuple[str, ...]) -> str:
    rendered = ", ".join(f"'{value}'" for value in values)
    return f"{column} IN ({rendered})"


def upgrade() -> None:
    op.create_table(
        "sessions",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("merchant_id", postgresql.UUID(as_uuid=True), nullable=False),
        # Display state (ADR-010). The Policy Engine never reads it and no
        # approval is ever derived from it (ADR-007).
        sa.Column(
            "conversation_state",
            sa.String(length=48),
            server_default=sa.text("'NEW_SESSION'"),
            nullable=False,
        ),
        # A§37: the structured intent accumulated across turns. Validated model
        # output, never raw text, and authorizing nothing by itself.
        sa.Column(
            "intent",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "last_seen_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_sessions"),
        sa.ForeignKeyConstraint(
            ["merchant_id"],
            ["merchants.id"],
            name="fk_sessions_merchant_id_merchants",
            ondelete="CASCADE",
        ),
        sa.CheckConstraint(
            _in_list("conversation_state", CONVERSATION_STATES),
            name="conversation_state_is_known",
        ),
        sa.CheckConstraint("jsonb_typeof(intent) = 'object'", name="intent_is_an_object"),
    )
    # Every read is "this session, for this merchant" — merchant scoping is
    # injected server-side on every call (ADR-002), so it is part of the lookup
    # rather than a filter applied afterwards.
    op.create_index("ix_sessions_merchant_id", "sessions", ["merchant_id"])

    op.create_table(
        "session_messages",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("content", sa.Text(), nullable=True),
        # A tool call or a tool result, structured. Keeping it out of `content`
        # is what stops a tool result becoming a sentence someone has to parse.
        sa.Column("tool_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_session_messages"),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["sessions.id"],
            name="fk_session_messages_session_id_sessions",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "session_id", "sequence", name="uq_session_messages_session_id_sequence"
        ),
        sa.CheckConstraint(_in_list("role", SESSION_MESSAGE_ROLES), name="role_is_known"),
        sa.CheckConstraint("sequence >= 0", name="sequence_is_not_negative"),
        sa.CheckConstraint(
            "content IS NOT NULL OR tool_payload IS NOT NULL",
            name="message_carries_content_or_payload",
        ),
    )


def downgrade() -> None:
    op.drop_table("session_messages")
    op.drop_index("ix_sessions_merchant_id", table_name="sessions")
    op.drop_table("sessions")
