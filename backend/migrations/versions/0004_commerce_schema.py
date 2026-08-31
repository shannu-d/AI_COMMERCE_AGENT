"""commerce schema: the nine tables ADR-006 designs (M6).

The money path's storage, created before any of it can be written to. Nothing
here is reachable from the application yet: M6 is a schema milestone, and the
Cart Service, the Policy Engine and the Order Service arrive in M7, M9 and M10.

Two tables came forward to M5 in ``0003`` - ``sessions`` and ``session_messages``
- because AGENT-01 had to close open question C3 and a runtime cannot do that
with a dictionary. These nine are the rest.

Three constraints carry more weight than the others and are worth finding here
rather than in a service:

* ``orders.approval_id`` is ``NOT NULL``. The database itself refuses to store
  an unapproved order. Test fixtures must therefore construct a real approval
  before they can create an order, which is friction, and it is exactly the
  friction the constraint exists to create.
* ``UNIQUE(provider, event_id)`` on ``webhook_events`` is the deduplication key
  that makes at-least-once delivery safe (P§25, P§26). A read-then-write check
  has a race; a unique constraint does not.
* The two **partial** unique indexes - one active cart per session, one approval
  per cart version - are partial because both tables accumulate history. A cart
  gains ORDERED and ABANDONED rows; an approval gains SUPERSEDED and EXPIRED
  ones, and ADR-014's price-drift recovery needs that history readable.

Every enumerated ``CHECK`` is rendered from a tuple in ``app.domain.commerce``,
so the application and the database cannot disagree about the legal values, and
``tests/db/test_migrations.py`` diffs this DDL against the compiled model
metadata clause by clause.

Revision ID: 0004
Revises: 0003
Created: 2026-09-01
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "carts",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("merchant_id", sa.UUID(), nullable=False),
        sa.Column("session_id", sa.UUID(), nullable=False),
        sa.Column(
            "status", sa.String(length=24), server_default=sa.text("'ACTIVE'"), nullable=False
        ),
        sa.Column("version", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column(
            "subtotal_amount",
            sa.Numeric(precision=12, scale=2),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column(
            "total_amount",
            sa.Numeric(precision=12, scale=2),
            server_default=sa.text("0"),
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
        sa.CheckConstraint(
            "status IN ('ACTIVE', 'ORDERED', 'ABANDONED')", name=op.f("ck_carts_status_is_known")
        ),
        sa.CheckConstraint("subtotal_amount >= 0", name=op.f("ck_carts_subtotal_is_not_negative")),
        sa.CheckConstraint("total_amount >= 0", name=op.f("ck_carts_total_is_not_negative")),
        sa.CheckConstraint("version >= 1", name=op.f("ck_carts_version_starts_at_one")),
        sa.ForeignKeyConstraint(
            ["merchant_id"], ["merchants.id"], name=op.f("fk_carts_merchant_id_merchants")
        ),
        sa.ForeignKeyConstraint(
            ["session_id"], ["sessions.id"], name=op.f("fk_carts_session_id_sessions")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_carts")),
    )
    op.create_index(
        "uq_carts_session_id_active",
        "carts",
        ["session_id"],
        unique=True,
        postgresql_where=sa.text("status = 'ACTIVE'"),
    )
    op.create_table(
        "approvals",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("session_id", sa.UUID(), nullable=False),
        sa.Column("cart_id", sa.UUID(), nullable=False),
        sa.Column("cart_version", sa.Integer(), nullable=False),
        sa.Column("approved_total", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("items_fingerprint", sa.CHAR(length=64), nullable=False),
        sa.Column(
            "status", sa.String(length=16), server_default=sa.text("'PENDING'"), nullable=False
        ),
        sa.Column("superseded_by_id", sa.UUID(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status <> 'APPROVED' OR approved_at IS NOT NULL",
            name=op.f("ck_approvals_approved_rows_carry_a_timestamp"),
        ),
        sa.CheckConstraint(
            "status IN ('PENDING', 'APPROVED', 'REJECTED', 'EXPIRED', 'SUPERSEDED')",
            name=op.f("ck_approvals_status_is_known"),
        ),
        sa.CheckConstraint(
            "approved_total >= 0", name=op.f("ck_approvals_approved_total_is_not_negative")
        ),
        sa.CheckConstraint(
            "cart_version >= 1", name=op.f("ck_approvals_cart_version_starts_at_one")
        ),
        sa.ForeignKeyConstraint(["cart_id"], ["carts.id"], name=op.f("fk_approvals_cart_id_carts")),
        sa.ForeignKeyConstraint(
            ["session_id"], ["sessions.id"], name=op.f("fk_approvals_session_id_sessions")
        ),
        sa.ForeignKeyConstraint(
            ["superseded_by_id"],
            ["approvals.id"],
            name=op.f("fk_approvals_superseded_by_id_approvals"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_approvals")),
    )
    op.create_index(
        "uq_approvals_cart_id_cart_version_approved",
        "approvals",
        ["cart_id", "cart_version"],
        unique=True,
        postgresql_where=sa.text("status = 'APPROVED'"),
    )
    op.create_table(
        "idempotency_keys",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("key", sa.String(length=128), nullable=False),
        sa.Column("scope", sa.String(length=32), nullable=False),
        sa.Column("session_id", sa.UUID(), nullable=False),
        sa.Column("cart_id", sa.UUID(), nullable=False),
        sa.Column("cart_version", sa.Integer(), nullable=False),
        sa.Column("approved_total", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column(
            "status", sa.String(length=16), server_default=sa.text("'RESERVED'"), nullable=False
        ),
        sa.Column("response_snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "scope IN ('ORDER_CREATION')", name=op.f("ck_idempotency_keys_scope_is_known")
        ),
        sa.CheckConstraint(
            "status IN ('RESERVED', 'COMPLETED', 'FAILED')",
            name=op.f("ck_idempotency_keys_status_is_known"),
        ),
        sa.CheckConstraint(
            "approved_total >= 0", name=op.f("ck_idempotency_keys_approved_total_is_not_negative")
        ),
        sa.CheckConstraint(
            "cart_version >= 1", name=op.f("ck_idempotency_keys_cart_version_starts_at_one")
        ),
        sa.ForeignKeyConstraint(
            ["cart_id"], ["carts.id"], name=op.f("fk_idempotency_keys_cart_id_carts")
        ),
        sa.ForeignKeyConstraint(
            ["session_id"], ["sessions.id"], name=op.f("fk_idempotency_keys_session_id_sessions")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_idempotency_keys")),
        sa.UniqueConstraint("key", name=op.f("uq_idempotency_keys_key")),
    )
    op.create_table(
        "cart_items",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("cart_id", sa.UUID(), nullable=False),
        sa.Column("variant_id", sa.UUID(), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("unit_price_snapshot", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("line_total", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
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
        sa.CheckConstraint(
            "line_total >= 0", name=op.f("ck_cart_items_line_total_is_not_negative")
        ),
        sa.CheckConstraint("quantity > 0", name=op.f("ck_cart_items_quantity_is_positive")),
        sa.CheckConstraint(
            "unit_price_snapshot >= 0", name=op.f("ck_cart_items_unit_price_is_not_negative")
        ),
        sa.ForeignKeyConstraint(
            ["cart_id"], ["carts.id"], name=op.f("fk_cart_items_cart_id_carts"), ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["variant_id"],
            ["product_variants.id"],
            name=op.f("fk_cart_items_variant_id_product_variants"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_cart_items")),
        sa.UniqueConstraint("cart_id", "variant_id", name=op.f("uq_cart_items_cart_id_variant_id")),
    )
    op.create_table(
        "orders",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("merchant_id", sa.UUID(), nullable=False),
        sa.Column("session_id", sa.UUID(), nullable=False),
        sa.Column("cart_id", sa.UUID(), nullable=False),
        sa.Column("cart_version", sa.Integer(), nullable=False),
        sa.Column("approval_id", sa.UUID(), nullable=False),
        sa.Column("idempotency_key_id", sa.UUID(), nullable=False),
        sa.Column(
            "status",
            sa.String(length=32),
            server_default=sa.text("'ORDER_CREATED'"),
            nullable=False,
        ),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("subtotal_amount", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("total_amount", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("total_amount_minor", sa.BigInteger(), nullable=False),
        sa.Column("razorpay_order_id", sa.String(length=64), nullable=True),
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
        sa.CheckConstraint(
            "status IN ('ORDER_CREATED', 'RAZORPAY_ORDER_CREATED', 'PAYMENT_PENDING', 'PAYMENT_CONFIRMED', 'PAYMENT_FAILED', 'ORDER_FAILED', 'CANCELLED')",
            name=op.f("ck_orders_status_is_known"),
        ),
        sa.CheckConstraint("cart_version >= 1", name=op.f("ck_orders_cart_version_starts_at_one")),
        sa.CheckConstraint("subtotal_amount >= 0", name=op.f("ck_orders_subtotal_is_not_negative")),
        sa.CheckConstraint("total_amount >= 0", name=op.f("ck_orders_total_is_not_negative")),
        sa.CheckConstraint(
            "total_amount_minor >= 0", name=op.f("ck_orders_total_minor_is_not_negative")
        ),
        sa.ForeignKeyConstraint(
            ["approval_id"], ["approvals.id"], name=op.f("fk_orders_approval_id_approvals")
        ),
        sa.ForeignKeyConstraint(["cart_id"], ["carts.id"], name=op.f("fk_orders_cart_id_carts")),
        sa.ForeignKeyConstraint(
            ["idempotency_key_id"],
            ["idempotency_keys.id"],
            name=op.f("fk_orders_idempotency_key_id_idempotency_keys"),
        ),
        sa.ForeignKeyConstraint(
            ["merchant_id"], ["merchants.id"], name=op.f("fk_orders_merchant_id_merchants")
        ),
        sa.ForeignKeyConstraint(
            ["session_id"], ["sessions.id"], name=op.f("fk_orders_session_id_sessions")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_orders")),
        sa.UniqueConstraint("idempotency_key_id", name=op.f("uq_orders_idempotency_key_id")),
        sa.UniqueConstraint("razorpay_order_id", name=op.f("uq_orders_razorpay_order_id")),
    )
    op.create_table(
        "order_items",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("order_id", sa.UUID(), nullable=False),
        sa.Column("variant_id", sa.UUID(), nullable=False),
        sa.Column("sku", sa.String(length=64), nullable=False),
        sa.Column("product_name", sa.String(length=200), nullable=False),
        sa.Column("variant_name", sa.String(length=200), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("unit_price", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("line_total", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "line_total >= 0", name=op.f("ck_order_items_line_total_is_not_negative")
        ),
        sa.CheckConstraint("quantity > 0", name=op.f("ck_order_items_quantity_is_positive")),
        sa.CheckConstraint(
            "unit_price >= 0", name=op.f("ck_order_items_unit_price_is_not_negative")
        ),
        sa.ForeignKeyConstraint(
            ["order_id"],
            ["orders.id"],
            name=op.f("fk_order_items_order_id_orders"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["variant_id"],
            ["product_variants.id"],
            name=op.f("fk_order_items_variant_id_product_variants"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_order_items")),
        sa.UniqueConstraint(
            "order_id", "variant_id", name=op.f("uq_order_items_order_id_variant_id")
        ),
    )
    op.create_table(
        "payments",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("order_id", sa.UUID(), nullable=False),
        sa.Column("razorpay_payment_id", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("amount", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("amount_minor", sa.BigInteger(), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("method", sa.String(length=32), nullable=True),
        sa.Column("failure_reason", sa.Text(), nullable=True),
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
        sa.CheckConstraint(
            "status IN ('CREATED', 'AUTHORIZED', 'CAPTURED', 'FAILED', 'REFUNDED')",
            name=op.f("ck_payments_status_is_known"),
        ),
        sa.CheckConstraint("amount >= 0", name=op.f("ck_payments_amount_is_not_negative")),
        sa.CheckConstraint(
            "amount_minor >= 0", name=op.f("ck_payments_amount_minor_is_not_negative")
        ),
        sa.ForeignKeyConstraint(
            ["order_id"], ["orders.id"], name=op.f("fk_payments_order_id_orders")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_payments")),
        sa.UniqueConstraint("razorpay_payment_id", name=op.f("uq_payments_razorpay_payment_id")),
    )
    op.create_index("ix_payments_order_id", "payments", ["order_id"], unique=False)
    op.create_table(
        "webhook_events",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column(
            "provider", sa.String(length=24), server_default=sa.text("'razorpay'"), nullable=False
        ),
        sa.Column("event_id", sa.String(length=128), nullable=False),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("signature", sa.String(length=256), nullable=False),
        sa.Column("raw_body", sa.Text(), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "status", sa.String(length=16), server_default=sa.text("'RECEIVED'"), nullable=False
        ),
        sa.Column("order_id", sa.UUID(), nullable=True),
        sa.Column(
            "received_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('RECEIVED', 'PROCESSED', 'IGNORED', 'FAILED')",
            name=op.f("ck_webhook_events_status_is_known"),
        ),
        sa.ForeignKeyConstraint(
            ["order_id"], ["orders.id"], name=op.f("fk_webhook_events_order_id_orders")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_webhook_events")),
        sa.UniqueConstraint(
            "provider", "event_id", name=op.f("uq_webhook_events_provider_event_id")
        ),
    )
    op.create_index("ix_webhook_events_order_id", "webhook_events", ["order_id"], unique=False)
    op.create_table(
        "audit_events",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("seq", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("event_type", sa.String(length=48), nullable=False),
        sa.Column("actor", sa.String(length=16), nullable=False),
        sa.Column("session_id", sa.UUID(), nullable=True),
        sa.Column("cart_id", sa.UUID(), nullable=True),
        sa.Column("order_id", sa.UUID(), nullable=True),
        sa.Column("payment_id", sa.UUID(), nullable=True),
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
        sa.CheckConstraint(
            "actor IN ('USER', 'AGENT', 'SYSTEM', 'RAZORPAY')",
            name=op.f("ck_audit_events_actor_is_known"),
        ),
        sa.CheckConstraint(
            "event_type IN ('CART_CREATED', 'USER_APPROVED', 'POLICY_PASS', 'POLICY_FAIL', 'ORDER_CREATED', 'RAZORPAY_ORDER_CREATED', 'CHECKOUT_STARTED', 'PAYMENT_WEBHOOK_RECEIVED', 'PAYMENT_CONFIRMED', 'PAYMENT_FAILED', 'PRICE_CHANGED', 'INVENTORY_FAILURE', 'APPROVAL_SUPERSEDED', 'APPROVAL_EXPIRED', 'WEBHOOK_SIGNATURE_REJECTED', 'WEBHOOK_DUPLICATE_IGNORED')",
            name=op.f("ck_audit_events_event_type_is_known"),
        ),
        sa.CheckConstraint(
            "jsonb_typeof(payload) = 'object'", name=op.f("ck_audit_events_payload_is_an_object")
        ),
        sa.ForeignKeyConstraint(
            ["cart_id"], ["carts.id"], name=op.f("fk_audit_events_cart_id_carts")
        ),
        sa.ForeignKeyConstraint(
            ["order_id"], ["orders.id"], name=op.f("fk_audit_events_order_id_orders")
        ),
        sa.ForeignKeyConstraint(
            ["payment_id"], ["payments.id"], name=op.f("fk_audit_events_payment_id_payments")
        ),
        sa.ForeignKeyConstraint(
            ["session_id"], ["sessions.id"], name=op.f("fk_audit_events_session_id_sessions")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_audit_events")),
        sa.UniqueConstraint("seq", name=op.f("uq_audit_events_seq")),
    )
    op.create_index("ix_audit_events_order_id", "audit_events", ["order_id"], unique=False)
    op.create_index("ix_audit_events_session_id", "audit_events", ["session_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_audit_events_session_id", table_name="audit_events")
    op.drop_index("ix_audit_events_order_id", table_name="audit_events")
    op.drop_table("audit_events")
    op.drop_index("ix_webhook_events_order_id", table_name="webhook_events")
    op.drop_table("webhook_events")
    op.drop_index("ix_payments_order_id", table_name="payments")
    op.drop_table("payments")
    op.drop_table("order_items")
    op.drop_table("orders")
    op.drop_table("cart_items")
    op.drop_table("idempotency_keys")
    op.drop_index(
        "uq_approvals_cart_id_cart_version_approved",
        table_name="approvals",
        postgresql_where=sa.text("status = 'APPROVED'"),
    )
    op.drop_table("approvals")
    op.drop_index(
        "uq_carts_session_id_active",
        table_name="carts",
        postgresql_where=sa.text("status = 'ACTIVE'"),
    )
    op.drop_table("carts")
