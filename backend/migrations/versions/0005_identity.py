"""identity: users, auth_tokens, and sessions.user_id (M17, ADR-023).

Authentication, as ADR-006 said it would arrive: *"a `users` table and a nullable
foreign key"*.

The whole change is two new tables and **one nullable column on an existing
one**. `carts` and `orders` are not touched, and neither is any existing row's
meaning: both already point at `sessions`, so ownership derives through
``sessions.user_id`` and an anonymous session simply keeps ``NULL`` — which is
what it always was. There is no data migration.

Two constraints carry the design:

* ``(role = 'MERCHANT' AND merchant_id IS NOT NULL) OR (role = 'CUSTOMER' AND
  merchant_id IS NULL)`` — the role/merchant pairing lives in the database, so a
  customer with a merchant, or a merchant administrator with none, is unstorable
  rather than merely discouraged.
* ``UNIQUE(auth_tokens.token_hash)`` — the token itself is never stored, only its
  SHA-256. A copy of this table yields no usable bearer token, and revocation is
  a column rather than a cache invalidation (ADR-023 §4).

The enumerated ``CHECK`` on ``users.role`` is rendered from ``USER_ROLES`` in
``app.domain.identity``, the same arrangement ``0004`` uses, so this DDL and the
compiled model metadata cannot drift — ``tests/db/test_migrations.py`` diffs
them clause by clause.

Revision ID: 0005
Revises: 0004
Created: 2026-09-04
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from app.db.models._enums import in_list
from app.domain.identity import USER_ROLES

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("merchant_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("display_name", sa.String(length=120), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
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
        sa.CheckConstraint(in_list("role", USER_ROLES), name="role_is_known"),
        sa.CheckConstraint(
            "(role = 'MERCHANT' AND merchant_id IS NOT NULL) "
            "OR (role = 'CUSTOMER' AND merchant_id IS NULL)",
            name="merchant_role_has_a_merchant",
        ),
        sa.CheckConstraint("email = lower(email)", name="email_is_lowercase"),
        sa.CheckConstraint("length(password_hash) > 0", name="password_hash_is_present"),
        sa.ForeignKeyConstraint(
            ["merchant_id"],
            ["merchants.id"],
            name=op.f("fk_users_merchant_id_merchants"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_users")),
        sa.UniqueConstraint("email", name=op.f("uq_users_email")),
    )
    op.create_index("ix_users_merchant_id", "users", ["merchant_id"], unique=False)

    op.create_table(
        "auth_tokens",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "issued_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("expires_at > issued_at", name="expiry_follows_issue"),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_auth_tokens_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_auth_tokens")),
        sa.UniqueConstraint("token_hash", name=op.f("uq_auth_tokens_token_hash")),
    )
    op.create_index("ix_auth_tokens_user_id", "auth_tokens", ["user_id"], unique=False)

    # The one change to an existing table. Nullable, so every row that already
    # exists stays exactly as valid as it was: an anonymous session.
    op.add_column(
        "sessions", sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=True)
    )
    op.create_foreign_key(
        op.f("fk_sessions_user_id_users"),
        "sessions",
        "users",
        ["user_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_sessions_user_id", "sessions", ["user_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_sessions_user_id", table_name="sessions")
    op.drop_constraint(op.f("fk_sessions_user_id_users"), "sessions", type_="foreignkey")
    op.drop_column("sessions", "user_id")

    op.drop_index("ix_auth_tokens_user_id", table_name="auth_tokens")
    op.drop_table("auth_tokens")

    op.drop_index("ix_users_merchant_id", table_name="users")
    op.drop_table("users")
