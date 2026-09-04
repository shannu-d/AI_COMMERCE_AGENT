"""merchant_activity: an append-only record of dashboard writes (ADR-023 §7).

One table, and nothing else changes.

**Why not `audit_events`.** That table reconstructs how one *transaction*
reached its outcome: every row hangs off a session, a cart, an order or a
payment, and its vocabulary is RZP-07's twelve money-path events plus four
failure cases. A price edit has none of those anchors. Folding administration
into it would mean widening two `CHECK` constraints, adding two columns null for
every existing row, and leaving one log answering two unrelated questions — so
reconstructing a purchase would mean filtering out stock edits first.

**What the shape guarantees.** `seq` is a total order, because two edits inside
one transaction share a timestamp. `actor_user_id` is `ON DELETE SET NULL` and
`actor_email` is copied in at write time, so removing an administrator does not
silently rewrite the history of what they changed. `entity_id` deliberately has
no foreign key: the record of a product's creation must outlive the product.

Both enumerated `CHECK`s render from `app.domain.activity`, the arrangement
`0004` and `0005` use, so this DDL and the compiled model metadata cannot drift
— `tests/db/test_migrations.py` diffs them clause by clause.

Revision ID: 0006
Revises: 0005
Created: 2026-09-04
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from app.db.models._enums import in_list
from app.domain.activity import MERCHANT_ACTIONS, MERCHANT_ENTITY_TYPES

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "merchant_activity",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("seq", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("merchant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("actor_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("actor_email", sa.String(length=320), nullable=False),
        sa.Column("action", sa.String(length=48), nullable=False),
        sa.Column("entity_type", sa.String(length=32), nullable=False),
        sa.Column("entity_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("subject", sa.String(length=200), nullable=True),
        sa.Column(
            "payload",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(in_list("action", MERCHANT_ACTIONS), name="action_is_known"),
        sa.CheckConstraint(
            in_list("entity_type", MERCHANT_ENTITY_TYPES), name="entity_type_is_known"
        ),
        sa.CheckConstraint("jsonb_typeof(payload) = 'object'", name="payload_is_an_object"),
        sa.ForeignKeyConstraint(
            ["merchant_id"],
            ["merchants.id"],
            name=op.f("fk_merchant_activity_merchant_id_merchants"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["actor_user_id"],
            ["users.id"],
            name=op.f("fk_merchant_activity_actor_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_merchant_activity")),
        sa.UniqueConstraint("seq", name=op.f("uq_merchant_activity_seq")),
    )
    op.create_index(
        "ix_merchant_activity_actor", "merchant_activity", ["actor_user_id"], unique=False
    )
    op.create_index(
        "ix_merchant_activity_merchant_seq",
        "merchant_activity",
        ["merchant_id", "seq"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_merchant_activity_merchant_seq", table_name="merchant_activity")
    op.drop_index("ix_merchant_activity_actor", table_name="merchant_activity")
    op.drop_table("merchant_activity")
