"""The catalog schema, asserted against the specification.

These run without a database. SQLAlchemy metadata is the same object the
migrations and the application both build from, so asserting against it proves
the schema's shape — and asserting against the compiled PostgreSQL DDL proves
what will actually be executed.

Each test names the section of architecture.md it enforces, so a future change
that contradicts the specification fails with a citation rather than a
surprise.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy import Numeric
from sqlalchemy.dialects import postgresql
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.schema import CreateTable

from app.config import BACKEND_DIR
from app.db.base import Base
from app.db.models import CATALOG_TABLES, COMMERCE_TABLES, IDENTITY_TABLES, SESSION_TABLES

CATALOG_TABLE_SET = set(CATALOG_TABLES)


def table(name: str):
    return Base.metadata.tables[name]


def constraint_names(name: str) -> set[str]:
    return {c.name for c in table(name).constraints if c.name}


def index_names(name: str) -> set[str]:
    return {ix.name for ix in table(name).indexes}


def ddl(name: str) -> str:
    return str(CreateTable(table(name)).compile(dialect=postgresql.dialect()))


# --------------------------------------------------------------------------
# D§3: the seven Phase-1 tables, and nothing else
# --------------------------------------------------------------------------


def test_the_seven_specified_catalog_tables_exist() -> None:
    assert CATALOG_TABLES == (
        "merchants",
        "categories",
        "products",
        "product_variants",
        "inventory",
        "compatibility_rules",
        "product_relationships",
    )
    assert CATALOG_TABLE_SET <= set(Base.metadata.tables)


def test_the_commerce_tables_arrived_with_m6() -> None:
    """The M6 shape of the guard that used to say these must not exist.

    D§36 and D§39 keep commerce out of the *catalog* milestone, and that held
    through M5. M6 is the milestone that adds it, so "they must not exist" is no
    longer the rule; what replaces it is that all nine are present, because a
    schema milestone that shipped eight of them would leave the ninth to be
    discovered by whichever service needed it first.
    """
    assert set(COMMERCE_TABLES) <= set(Base.metadata.tables)


def test_no_commerce_service_or_policy_module_has_been_created_early() -> None:
    """What the old table guard was really protecting.

    M6 was schema and nothing else. M7 added the Cart Service and M8 approvals,
    neither of which moves money; M9 adds the Policy Engine, which decides
    whether money may move without moving any, and M10 the Order Service, which
    creates the internal order before any provider is called, and M11 the
    Razorpay client, M12 the verified-webhook handler and M13 the audit writer.
    Every module this guard once named now exists; the names below are things the
    MVP forecloses (ADR-006). The specification is emphatic (D§39, A§58, F§37)
    that the money path must not be coded before its decisions exist. Tables are
    inert; a service that writes to them is not.
    """
    packages = [
        name
        for name in ("app/services/refund_service.py", "app/api/routes/admin.py")
        if (BACKEND_DIR / name).exists()
    ]

    assert packages == []


def test_the_session_tables_arrived_with_the_agent_runtime() -> None:
    """The other half of the guard above, and the reason the two moved.

    Open question C3 - session and approval persistence - is closed by ADR-006
    as *PostgreSQL*, and `04-task-breakdown.md` gives AGENT-01, the M5 runtime
    skeleton, the job of closing it. A runtime cannot close C3 with a
    dictionary, and ADR-006 states the objection to trying: in-memory session
    state would make the price-drift and duplicate-request scenarios untestable
    across processes.
    """
    assert set(SESSION_TABLES) <= set(Base.metadata.tables)


def test_no_table_beyond_the_catalog_the_vocabulary_and_the_commerce_schema_exists() -> None:
    """ADR-003, ADR-006 and ADR-023. Any other extra table is unintended scope.

    Every addition beyond the specified seven names the decision that put it
    there: `compatibility_targets` has ADR-003, the session and commerce tables
    have ADR-006, and `users` / `auth_tokens` have ADR-023. A table outside this
    set is one nobody decided on.

    Note what is *not* here: no `customers` table, and no ownership column on
    `carts` or `orders`. ADR-023 derives ownership through `sessions.user_id`,
    so authentication cost the commerce schema one nullable column and no data
    migration.
    """
    extra = set(Base.metadata.tables) - CATALOG_TABLE_SET
    assert extra == {
        "compatibility_targets",
        *SESSION_TABLES,
        *COMMERCE_TABLES,
        *IDENTITY_TABLES,
    }


# --------------------------------------------------------------------------
# D§21: primary keys
# --------------------------------------------------------------------------


@pytest.mark.parametrize("name", [*CATALOG_TABLES, "compatibility_targets"])
def test_primary_key_is_a_single_uuid_column_named_id(name: str) -> None:
    pk = table(name).primary_key
    assert [c.name for c in pk.columns] == ["id"]
    assert isinstance(pk.columns["id"].type, postgresql.UUID)
    assert pk.name == f"pk_{name}"


def test_sku_is_not_a_primary_key() -> None:
    """D§21: SKU is a business identifier, not database identity."""
    pk_columns = {c.name for c in table("product_variants").primary_key.columns}
    assert "sku" not in pk_columns


# --------------------------------------------------------------------------
# D§22: foreign keys
# --------------------------------------------------------------------------


def foreign_key_pairs(name: str) -> set[tuple[str, str]]:
    return {
        (fk.parent.name, f"{fk.column.table.name}.{fk.column.name}")
        for fk in table(name).foreign_keys
    }


def test_every_foreign_key_d22_specifies_exists() -> None:
    specified = {
        "categories": {("merchant_id", "merchants.id"), ("parent_id", "categories.id")},
        "products": {("merchant_id", "merchants.id"), ("category_id", "categories.id")},
        "product_variants": {("merchant_id", "merchants.id"), ("product_id", "products.id")},
        "inventory": {("variant_id", "product_variants.id")},
        "compatibility_rules": {("product_id", "products.id")},
        "product_relationships": {
            ("source_product_id", "products.id"),
            ("target_product_id", "products.id"),
        },
    }
    for name, pairs in specified.items():
        assert pairs <= foreign_key_pairs(name), f"{name} is missing a D§22 foreign key"


def test_products_and_variants_are_additionally_scoped_to_their_merchant() -> None:
    """Beyond D§22: a product cannot sit in another merchant's category.

    ADR-002 makes merchant scoping an invariant rather than a convention.
    """
    assert "fk_products_category_within_merchant" in ddl("products")
    assert "REFERENCES categories (merchant_id, id)" in ddl("products")

    assert "fk_product_variants_product_within_merchant" in ddl("product_variants")
    assert "REFERENCES products (merchant_id, id)" in ddl("product_variants")


# --------------------------------------------------------------------------
# D§23: unique constraints
# --------------------------------------------------------------------------


def test_unique_constraints_d23_specifies() -> None:
    assert "uq_categories_merchant_id_slug" in constraint_names("categories")
    assert "uq_products_merchant_id_slug" in constraint_names("products")
    assert "uq_product_variants_merchant_id_sku" in constraint_names("product_variants")
    assert "uq_inventory_variant_id" in constraint_names("inventory")


def test_two_merchants_may_reuse_a_sku() -> None:
    """D§10: SKU is unique per merchant, not globally."""
    unique = [
        c
        for c in table("product_variants").constraints
        if c.name == "uq_product_variants_merchant_id_sku"
    ]
    assert [c.name for c in unique[0].columns] == ["merchant_id", "sku"]


# --------------------------------------------------------------------------
# D§24: indexes
# --------------------------------------------------------------------------


def test_every_index_d24_specifies_exists() -> None:
    assert {
        "ix_products_merchant_id",
        "ix_products_category_id",
        "ix_products_merchant_id_category_id",
        "ix_products_is_active",
    } <= index_names("products")

    assert "ix_compatibility_rules_target_type_target_identifier" in index_names(
        "compatibility_rules"
    )
    assert "ix_product_relationships_source_product_id" in index_names("product_relationships")


def test_gin_indexes_on_products_are_deferred() -> None:
    """D§24: add them only when real query patterns justify them."""
    gin = [
        ix
        for ix in table("products").indexes
        if ix.dialect_options.get("postgresql", {}).get("using") == "gin"
    ]
    assert gin == []


def test_the_alias_index_is_gin_because_alias_lookup_is_the_query() -> None:
    """ADR-003: this is the query pattern the table exists to serve."""
    aliases = next(
        ix
        for ix in table("compatibility_targets").indexes
        if ix.name == "ix_compatibility_targets_aliases"
    )
    assert aliases.dialect_options["postgresql"]["using"] == "gin"


# --------------------------------------------------------------------------
# Types
# --------------------------------------------------------------------------


def test_price_is_numeric_12_2_and_returns_decimal() -> None:
    """D§8, ADR-008: no float ever touches a price."""
    price = table("product_variants").columns["price"]
    assert isinstance(price.type, Numeric)
    assert (price.type.precision, price.type.scale) == (12, 2)
    assert price.type.asdecimal is True
    assert price.type.python_type is Decimal
    assert price.nullable is False


def test_currency_is_explicit_wherever_money_is() -> None:
    """ADR-008: an amount is never stored without its currency."""
    for name in ("merchants", "product_variants"):
        assert table(name).columns["currency"].nullable is False


def test_attributes_are_jsonb_and_tags_are_a_text_array() -> None:
    """D§7, D§18."""
    assert isinstance(table("products").columns["attributes"].type, JSONB)
    assert isinstance(table("product_variants").columns["attributes"].type, JSONB)
    assert isinstance(table("compatibility_rules").columns["constraints"].type, JSONB)
    assert isinstance(table("products").columns["tags"].type, ARRAY)


def test_every_timestamp_is_timezone_aware() -> None:
    for name in (*CATALOG_TABLES, "compatibility_targets"):
        for column in table(name).columns:
            if column.name.endswith("_at"):
                assert column.type.timezone is True, f"{name}.{column.name} is naive"
                assert column.nullable is False


def test_inventory_has_updated_at_and_no_created_at() -> None:
    """D§11 lists updated_at only; the schema follows it."""
    columns = set(table("inventory").columns.keys())
    assert "updated_at" in columns
    assert "created_at" not in columns


def test_product_relationships_have_created_at_and_no_updated_at() -> None:
    """D§16 lists created_at only."""
    columns = set(table("product_relationships").columns.keys())
    assert "created_at" in columns
    assert "updated_at" not in columns


# --------------------------------------------------------------------------
# Check constraints
# --------------------------------------------------------------------------


def test_money_and_quantities_cannot_be_negative() -> None:
    assert "ck_product_variants_price_is_not_negative" in constraint_names("product_variants")
    assert "ck_inventory_quantity_is_not_negative" in constraint_names("inventory")
    assert "ck_inventory_reserved_quantity_is_not_negative" in constraint_names("inventory")


def test_available_quantity_cannot_go_negative() -> None:
    """D§11: available = quantity - reserved."""
    assert "ck_inventory_reserved_quantity_within_quantity" in constraint_names("inventory")


def test_compatibility_identifiers_must_be_canonical_tokens() -> None:
    """ADR-003: a resolution bug cannot write an unmatchable row."""
    names = constraint_names("compatibility_rules")
    assert "ck_compatibility_rules_target_identifier_is_canonical_token" in names
    assert "ck_compatibility_rules_target_type_is_known" in names


def test_rule_type_is_restricted_to_compatible() -> None:
    """ADR-003: a value the filter cannot interpret must not be storable."""
    assert "ck_compatibility_rules_rule_type_is_supported" in constraint_names(
        "compatibility_rules"
    )
    assert "rule_type IN ('compatible')" in ddl("compatibility_rules")


def test_relationship_type_is_restricted_to_the_specified_values() -> None:
    """D§16."""
    assert "relationship_type IN ('cross_sell', 'bundle', 'related')" in ddl(
        "product_relationships"
    )


def test_a_product_cannot_relate_to_itself() -> None:
    assert "ck_product_relationships_source_differs_from_target" in constraint_names(
        "product_relationships"
    )


def test_a_category_cannot_be_its_own_parent() -> None:
    assert "ck_categories_parent_is_not_self" in constraint_names("categories")


def test_slugs_must_be_canonical_tokens() -> None:
    """ADR-009/B2: slugs are the enum the agent's search tool chooses from."""
    assert "ck_categories_slug_is_canonical_token" in constraint_names("categories")
    assert "ck_products_slug_is_canonical_token" in constraint_names("products")


def test_skus_must_be_uppercase_tokens() -> None:
    assert "ck_product_variants_sku_is_uppercase_token" in constraint_names("product_variants")


def test_json_columns_must_hold_objects_not_arrays_or_scalars() -> None:
    for name, constraint in (
        ("products", "ck_products_attributes_is_object"),
        ("product_variants", "ck_product_variants_attributes_is_object"),
        ("compatibility_rules", "ck_compatibility_rules_constraints_is_object"),
    ):
        assert constraint in constraint_names(name)


# --------------------------------------------------------------------------
# Naming and portability
# --------------------------------------------------------------------------


def test_every_constraint_and_index_name_fits_postgres_identifier_limits() -> None:
    for name in Base.metadata.tables:
        for constraint in table(name).constraints:
            if constraint.name:
                assert len(constraint.name) <= 63, constraint.name
        for index in table(name).indexes:
            assert index.name is not None and len(index.name) <= 63, index.name


def test_index_space_names_are_unique_across_the_schema() -> None:
    """PostgreSQL puts indexes and unique constraints in one namespace."""
    names: list[str] = []
    for name in Base.metadata.tables:
        names.extend(
            c.name for c in table(name).constraints if c.name and c.name.startswith(("pk_", "uq_"))
        )
        names.extend(ix.name for ix in table(name).indexes if ix.name)
    assert len(names) == len(set(names))


# --------------------------------------------------------------------------
# Mapper configuration
# --------------------------------------------------------------------------


def test_every_orm_relationship_resolves() -> None:
    """Catches ambiguous joins without needing a database.

    SQLAlchemy configures mappers lazily, on first use, so a relationship whose
    join condition is ambiguous stays silent until something actually queries
    it. The composite merchant-scoping foreign keys (ADR-002) give several table
    pairs two foreign key paths, which is exactly the situation that produces
    AmbiguousForeignKeysError — so configuration is forced here instead of
    being discovered at runtime.
    """
    from sqlalchemy.orm import class_mapper, configure_mappers

    from app.db.models import (
        Category,
        CompatibilityRule,
        Inventory,
        Merchant,
        Product,
        ProductRelationship,
        ProductVariant,
    )

    configure_mappers()

    # configure_mappers() raising is the real guard, but assert the join
    # conditions actually resolved so the test cannot pass vacuously if
    # configuration was already done and cached by an earlier test.
    checked = 0
    for model in (
        Merchant,
        Category,
        Product,
        ProductVariant,
        Inventory,
        CompatibilityRule,
        ProductRelationship,
    ):
        for relation in class_mapper(model).relationships:
            assert relation.primaryjoin is not None, f"{model.__name__}.{relation.key}"
            checked += 1
    assert checked >= 15, f"only {checked} relationships checked; models may have been removed"
