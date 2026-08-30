"""Phase-1 catalog schema: the seven tables architecture.md specifies.

    merchants → categories → products → product_variants → inventory
    products  → compatibility_rules
    products  → product_relationships

Specified at column level in architecture.md D§4–D§16, with primary keys D§21,
foreign keys D§22, unique constraints D§23 and indexes D§24. D§36 and D§39
exclude every commerce table from this milestone, and none is created here.

Constraint names are spelled out rather than left to PostgreSQL, so that a
database built from these migrations is byte-identical in its constraint names
to one built from the SQLAlchemy metadata. A test asserts that equality; drift
between the models and this file is a test failure, not a surprise in
production.

Revision ID: 0001
Revises:
Created: 2026-08-30
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Literals rather than imports from ``app``: a migration is a snapshot of what
# the schema looked like at this revision, and must not change retroactively
# when a constant in the application changes.
CANONICAL_TOKEN = r"^[a-z0-9]+([-_][a-z0-9]+)*$"
SKU_TOKEN = r"^[A-Z0-9][A-Z0-9_-]*$"
CURRENCY = r"^[A-Z]{3}$"


def upgrade() -> None:
    # -- merchants (D§4) -----------------------------------------------------
    op.create_table(
        "merchants",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("currency", sa.String(length=3), server_default=sa.text("'INR'"), nullable=False),
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
        sa.PrimaryKeyConstraint("id", name="pk_merchants"),
        sa.UniqueConstraint("name", name="uq_merchants_name"),
        sa.CheckConstraint(f"currency ~ '{CURRENCY}'", name="currency_is_iso4217"),
    )

    # -- categories (D§5) ----------------------------------------------------
    op.create_table(
        "categories",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("merchant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("slug", sa.String(length=128), nullable=False),
        sa.Column("parent_id", postgresql.UUID(as_uuid=True), nullable=True),
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
        sa.PrimaryKeyConstraint("id", name="pk_categories"),
        # D§23
        sa.UniqueConstraint("merchant_id", "slug", name="uq_categories_merchant_id_slug"),
        # Target for the composite foreign key on products.
        sa.UniqueConstraint("merchant_id", "id", name="uq_categories_merchant_id_id"),
        sa.CheckConstraint(f"slug ~ '{CANONICAL_TOKEN}'", name="slug_is_canonical_token"),
        sa.CheckConstraint("parent_id IS NULL OR parent_id <> id", name="parent_is_not_self"),
        # D§22
        sa.ForeignKeyConstraint(
            ["merchant_id"],
            ["merchants.id"],
            name="fk_categories_merchant_id_merchants",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["parent_id"],
            ["categories.id"],
            name="fk_categories_parent_id_categories",
            ondelete="SET NULL",
        ),
    )
    op.create_index("ix_categories_parent_id", "categories", ["parent_id"])

    # -- products (D§6, D§7) -------------------------------------------------
    op.create_table(
        "products",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("merchant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("category_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("slug", sa.String(length=160), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("brand", sa.String(length=128), nullable=True),
        sa.Column(
            "attributes",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "tags",
            postgresql.ARRAY(sa.Text()),
            server_default=sa.text("'{}'::text[]"),
            nullable=False,
        ),
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
        sa.PrimaryKeyConstraint("id", name="pk_products"),
        sa.UniqueConstraint("merchant_id", "slug", name="uq_products_merchant_id_slug"),
        sa.UniqueConstraint("merchant_id", "id", name="uq_products_merchant_id_id"),
        # A product's category must belong to the same merchant. The plain
        # category_id key below satisfies D§22; this one makes cross-merchant
        # assignment impossible rather than merely discouraged.
        sa.ForeignKeyConstraint(
            ["merchant_id", "category_id"],
            ["categories.merchant_id", "categories.id"],
            name="fk_products_category_within_merchant",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(f"slug ~ '{CANONICAL_TOKEN}'", name="slug_is_canonical_token"),
        sa.CheckConstraint("jsonb_typeof(attributes) = 'object'", name="attributes_is_object"),
        sa.ForeignKeyConstraint(
            ["merchant_id"],
            ["merchants.id"],
            name="fk_products_merchant_id_merchants",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["category_id"],
            ["categories.id"],
            name="fk_products_category_id_categories",
            ondelete="RESTRICT",
        ),
    )
    # D§24, verbatim.
    op.create_index("ix_products_merchant_id", "products", ["merchant_id"])
    op.create_index("ix_products_category_id", "products", ["category_id"])
    op.create_index(
        "ix_products_merchant_id_category_id", "products", ["merchant_id", "category_id"]
    )
    op.create_index("ix_products_is_active", "products", ["is_active"])

    # -- product_variants (D§8, D§10) ---------------------------------------
    op.create_table(
        "product_variants",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("merchant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("product_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("sku", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        # NUMERIC(12,2): the authoritative price. Integer minor units exist only
        # at the Razorpay boundary (ADR-008).
        sa.Column("price", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column(
            "attributes",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
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
        sa.PrimaryKeyConstraint("id", name="pk_product_variants"),
        # D§10, D§23, D§24: two merchants may reuse a SKU string.
        sa.UniqueConstraint("merchant_id", "sku", name="uq_product_variants_merchant_id_sku"),
        sa.ForeignKeyConstraint(
            ["merchant_id", "product_id"],
            ["products.merchant_id", "products.id"],
            name="fk_product_variants_product_within_merchant",
            ondelete="CASCADE",
        ),
        sa.CheckConstraint(f"sku ~ '{SKU_TOKEN}'", name="sku_is_uppercase_token"),
        sa.CheckConstraint("price >= 0", name="price_is_not_negative"),
        sa.CheckConstraint(f"currency ~ '{CURRENCY}'", name="currency_is_iso4217"),
        sa.CheckConstraint(
            "jsonb_typeof(attributes) = 'object'",
            name="attributes_is_object",
        ),
        sa.ForeignKeyConstraint(
            ["merchant_id"],
            ["merchants.id"],
            name="fk_product_variants_merchant_id_merchants",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["product_id"],
            ["products.id"],
            name="fk_product_variants_product_id_products",
            ondelete="CASCADE",
        ),
    )
    op.create_index("ix_product_variants_product_id", "product_variants", ["product_id"])
    op.create_index("ix_product_variants_is_active", "product_variants", ["is_active"])

    # -- inventory (D§11, D§12) ---------------------------------------------
    op.create_table(
        "inventory",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("variant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("quantity", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("reserved_quantity", sa.Integer(), server_default=sa.text("0"), nullable=False),
        # D§11 gives this table an updated_at and no created_at.
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_inventory"),
        # D§11, D§23: one inventory record per variant.
        sa.UniqueConstraint("variant_id", name="uq_inventory_variant_id"),
        sa.CheckConstraint("quantity >= 0", name="quantity_is_not_negative"),
        sa.CheckConstraint("reserved_quantity >= 0", name="reserved_quantity_is_not_negative"),
        # available_quantity = quantity - reserved_quantity, and must not be
        # negative.
        sa.CheckConstraint(
            "reserved_quantity <= quantity",
            name="reserved_quantity_within_quantity",
        ),
        sa.ForeignKeyConstraint(
            ["variant_id"],
            ["product_variants.id"],
            name="fk_inventory_variant_id_product_variants",
            ondelete="CASCADE",
        ),
    )

    # -- compatibility_rules (D§13, D§14, D§15) ------------------------------
    op.create_table(
        "compatibility_rules",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("product_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("target_type", sa.String(length=64), nullable=False),
        sa.Column("target_identifier", sa.String(length=128), nullable=False),
        sa.Column(
            "rule_type",
            sa.String(length=32),
            server_default=sa.text("'compatible'"),
            nullable=False,
        ),
        sa.Column(
            "constraints",
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
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_compatibility_rules"),
        sa.UniqueConstraint(
            "product_id",
            "target_type",
            "target_identifier",
            "rule_type",
            name="uq_compatibility_rules_product_target",
        ),
        sa.CheckConstraint(
            "target_type IN ('phone_model', 'laptop_model', 'device', 'device_port')",
            name="target_type_is_known",
        ),
        # ADR-003: identifiers are canonical tokens, so a resolution bug cannot
        # write an unmatchable row.
        sa.CheckConstraint(
            f"target_identifier ~ '{CANONICAL_TOKEN}'",
            name="target_identifier_is_canonical_token",
        ),
        # ADR-003: only 'compatible' in the MVP. A value the filter cannot
        # interpret is worse than a value that cannot be stored.
        sa.CheckConstraint(
            "rule_type IN ('compatible')",
            name="rule_type_is_supported",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(constraints) = 'object'",
            name="constraints_is_object",
        ),
        sa.ForeignKeyConstraint(
            ["product_id"],
            ["products.id"],
            name="fk_compatibility_rules_product_id_products",
            ondelete="CASCADE",
        ),
    )
    # D§24/D§25: makes "everything compatible with iphone_16" a lookup.
    op.create_index(
        "ix_compatibility_rules_target_type_target_identifier",
        "compatibility_rules",
        ["target_type", "target_identifier"],
    )
    op.create_index("ix_compatibility_rules_product_id", "compatibility_rules", ["product_id"])

    # -- product_relationships (D§16, D§17) ---------------------------------
    op.create_table(
        "product_relationships",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("source_product_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("target_product_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("relationship_type", sa.String(length=32), nullable=False),
        sa.Column("priority", sa.Integer(), server_default=sa.text("0"), nullable=False),
        # D§16 lists created_at only.
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_product_relationships"),
        sa.UniqueConstraint(
            "source_product_id",
            "target_product_id",
            "relationship_type",
            name="uq_product_relationships_pair_type",
        ),
        sa.CheckConstraint(
            "source_product_id <> target_product_id",
            name="source_differs_from_target",
        ),
        sa.CheckConstraint(
            "relationship_type IN ('cross_sell', 'bundle', 'related')",
            name="relationship_type_is_known",
        ),
        sa.CheckConstraint("priority >= 0", name="priority_is_not_negative"),
        sa.ForeignKeyConstraint(
            ["source_product_id"],
            ["products.id"],
            name="fk_product_relationships_source_product_id_products",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["target_product_id"],
            ["products.id"],
            name="fk_product_relationships_target_product_id_products",
            ondelete="CASCADE",
        ),
    )
    # D§24: relationships are always looked up from the source.
    op.create_index(
        "ix_product_relationships_source_product_id",
        "product_relationships",
        ["source_product_id"],
    )


def downgrade() -> None:
    # Reverse dependency order.
    op.drop_table("product_relationships")
    op.drop_table("compatibility_rules")
    op.drop_table("inventory")
    op.drop_table("product_variants")
    op.drop_table("products")
    op.drop_table("categories")
    op.drop_table("merchants")
