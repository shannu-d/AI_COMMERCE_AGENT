"""Catalog integrity against a real PostgreSQL instance.

Everything here is marked ``requires_db`` and **skips with a visible reason**
when no PostgreSQL is reachable. It is never silently passed, and never
redirected at a different engine — the schema depends on UUID, JSONB and TEXT[],
so a green run against SQLite would prove nothing (ADR-002).

What these prove that the offline tests cannot:

* the migrations apply for real, from zero, and can be rolled back;
* the constraints actually reject violations, rather than merely appearing in
  the DDL;
* the seed loads, and loading it twice leaves the same rows;
* catalog queries return deterministic results.

Run them with::

    docker compose up -d db
    cd backend && python -m pytest -m requires_db
"""

from __future__ import annotations

from collections.abc import Iterator
from decimal import Decimal

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.config import BACKEND_DIR
from app.db.models import (
    Category,
    CompatibilityRule,
    CompatibilityTarget,
    Inventory,
    Merchant,
    Product,
    ProductRelationship,
    ProductVariant,
)
from app.identifiers import DEFAULT_MERCHANT_ID, seed_id
from app.seed.circuitcraft import database_summary, seed_catalog
from app.seed.schema import CatalogSeed, load_catalog

pytestmark = pytest.mark.requires_db


@pytest.fixture(scope="module")
def migrated_engine(db_engine: Engine, database_url: str) -> Iterator[Engine]:
    """A database at ``head``, built from the migrations, and torn down after.

    Downgrading to base first means the run starts from nothing whatever the
    database happened to contain — which is what "a fresh database can be
    created from migrations" actually claims.
    """
    config = Config(str(BACKEND_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_DIR / "migrations"))
    config.cmd_opts = type("Opts", (), {"x": [f"url={database_url}"]})()  # type: ignore[assignment]

    command.downgrade(config, "base")
    command.upgrade(config, "head")
    yield db_engine
    command.downgrade(config, "base")


@pytest.fixture(scope="module")
def catalog() -> CatalogSeed:
    return load_catalog()


@pytest.fixture(scope="module")
def seeded(migrated_engine: Engine, catalog: CatalogSeed) -> Iterator[sessionmaker[Session]]:
    factory = sessionmaker(bind=migrated_engine, expire_on_commit=False, future=True)
    with factory() as session, session.begin():
        seed_catalog(session, catalog, DEFAULT_MERCHANT_ID)
    yield factory


@pytest.fixture
def session(seeded: sessionmaker[Session]) -> Iterator[Session]:
    """A session whose writes are always rolled back.

    Constraint tests deliberately provoke IntegrityError; each must leave the
    seeded catalog untouched for the next test.
    """
    with seeded() as active:
        yield active
        active.rollback()


# --------------------------------------------------------------------------
# Migrations
# --------------------------------------------------------------------------


def test_a_fresh_database_is_created_from_the_migrations(migrated_engine: Engine) -> None:
    """M1 exit criterion 1 and 2."""
    with migrated_engine.connect() as connection:
        tables = set(
            connection.execute(
                text(
                    "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'"
                )
            ).scalars()
        )

    assert {
        "merchants",
        "categories",
        "products",
        "product_variants",
        "inventory",
        "compatibility_rules",
        "product_relationships",
        "compatibility_targets",
        "alembic_version",
    } <= tables


def test_constraint_names_in_the_database_match_the_models(migrated_engine: Engine) -> None:
    """The names the offline tests assert are the names PostgreSQL really has."""
    with migrated_engine.connect() as connection:
        names = set(
            connection.execute(
                text(
                    "SELECT conname FROM pg_constraint c "
                    "JOIN pg_namespace n ON n.oid = c.connamespace "
                    "WHERE n.nspname = 'public'"
                )
            ).scalars()
        )

    assert {
        "pk_merchants",
        "uq_product_variants_merchant_id_sku",
        "uq_inventory_variant_id",
        "ck_product_variants_price_is_not_negative",
        "ck_inventory_reserved_quantity_within_quantity",
        "ck_compatibility_rules_rule_type_is_supported",
        "fk_products_category_within_merchant",
    } <= names


# --------------------------------------------------------------------------
# Seed
# --------------------------------------------------------------------------


def test_seed_loads_every_row(seeded: sessionmaker[Session], catalog: CatalogSeed) -> None:
    """M1 exit criterion 3."""
    with seeded() as session:
        counts = database_summary(session)

    assert counts["merchants"] == 1
    assert counts["categories"] == len(catalog.categories)
    assert counts["products"] == len(catalog.products)
    assert counts["product_variants"] == catalog.variant_count
    assert counts["inventory"] == catalog.variant_count
    assert counts["compatibility_rules"] == catalog.rule_count
    assert counts["product_relationships"] == len(catalog.relationships)
    assert counts["compatibility_targets"] == len(catalog.compatibility_targets)


def test_seeding_twice_changes_nothing(seeded: sessionmaker[Session], catalog: CatalogSeed) -> None:
    """Deterministic UUIDs make the loader idempotent (ADR-002)."""
    with seeded() as session:
        before = database_summary(session)

    with seeded() as session, session.begin():
        seed_catalog(session, catalog, DEFAULT_MERCHANT_ID)

    with seeded() as session:
        after = database_summary(session)

    assert before == after


def test_the_merchant_id_is_the_configured_one(seeded: sessionmaker[Session]) -> None:
    """ADR-002: merchant scoping is configuration, not discovery."""
    with seeded() as session:
        merchant = session.get(Merchant, DEFAULT_MERCHANT_ID)

    assert merchant is not None
    assert merchant.name == "EASY BUY"  # ADR-021: display name; the id is unchanged
    assert merchant.currency == "INR"


def test_price_round_trips_as_decimal(seeded: sessionmaker[Session]) -> None:
    """ADR-008: NUMERIC(12,2) in, Decimal out, no float anywhere."""
    with seeded() as session:
        variant = session.get(ProductVariant, seed_id("variant", "CASE-IP16-BLK"))

    assert variant is not None
    assert isinstance(variant.price, Decimal)
    assert variant.price == Decimal("999.00")


def test_jsonb_and_array_columns_round_trip(seeded: sessionmaker[Session]) -> None:
    with seeded() as session:
        product = session.get(Product, seed_id("product", "aerocase_pro"))

    assert product is not None
    assert product.attributes["material"] == "TPU"
    assert "iphone" in product.tags


# --------------------------------------------------------------------------
# Deterministic catalog queries — the shape M2 will build on
# --------------------------------------------------------------------------


def test_compatibility_lookup_returns_only_compatible_products(
    seeded: sessionmaker[Session],
) -> None:
    """R§5, D§15: an iPhone 15 case must not appear for an iPhone 16 buyer."""
    with seeded() as session:
        slugs = set(
            session.execute(
                select(Product.slug)
                .join(CompatibilityRule, CompatibilityRule.product_id == Product.id)
                .join(Category, Category.id == Product.category_id)
                .where(
                    Category.slug == "phone_case",
                    CompatibilityRule.target_identifier == "iphone_16",
                    CompatibilityRule.rule_type == "compatible",
                )
            ).scalars()
        )

    assert "aerocase_pro" in slugs
    assert "aerocase_pro_15" not in slugs


def test_the_worked_example_query_returns_the_expected_candidates(
    seeded: sessionmaker[Session],
) -> None:
    """ "A case for iPhone 16 under ₹1,500", as D§29 sequences it.

    Category, then budget, then compatibility, then inventory. The ranking that
    consumes this arrives in M3; what M1 owes is that the candidate set is
    correct and reproducible.
    """
    with seeded() as session:
        rows = session.execute(
            select(ProductVariant.sku, ProductVariant.price)
            .join(Product, Product.id == ProductVariant.product_id)
            .join(Category, Category.id == Product.category_id)
            .join(Inventory, Inventory.variant_id == ProductVariant.id)
            .join(CompatibilityRule, CompatibilityRule.product_id == Product.id)
            .where(
                Product.merchant_id == DEFAULT_MERCHANT_ID,
                Product.is_active.is_(True),
                ProductVariant.is_active.is_(True),
                Category.slug == "phone_case",
                ProductVariant.price <= Decimal("1500.00"),
                CompatibilityRule.target_identifier == "iphone_16",
                Inventory.quantity - Inventory.reserved_quantity >= 1,
            )
            .order_by(ProductVariant.price, ProductVariant.sku)
        ).all()

    skus = [sku for sku, _ in rows]

    # In stock, compatible, within budget.
    assert "CASE-IP16-BLK" in skus
    assert "CASE-IP16-BLU" in skus
    assert "CASE-IP16-SHD-BLK" in skus
    # Out of stock.
    assert "CASE-IP16-CLR" not in skus
    # Wrong device.
    assert "CASE-IP15-BLK" not in skus
    # Over budget.
    assert "CASE-IP16-LTR-BLK" not in skus

    # Deterministic ordering, and prices are Decimals.
    assert skus == sorted(skus, key=lambda s: (dict(rows)[s], s))
    assert all(isinstance(price, Decimal) for _, price in rows)


def test_a_resolvable_device_with_no_compatible_products_returns_nothing(
    seeded: sessionmaker[Session],
) -> None:
    """R§14: a genuine no-match, distinct from an unresolved device."""
    with seeded() as session:
        target = session.execute(
            select(CompatibilityTarget).where(CompatibilityTarget.canonical_identifier == "pixel_9")
        ).scalar_one()

        matches = session.execute(
            select(func.count())
            .select_from(CompatibilityRule)
            .where(CompatibilityRule.target_identifier == "pixel_9")
        ).scalar_one()

    assert target.display_name == "Google Pixel 9"
    assert matches == 0


def test_cross_sell_lookup_is_ordered_by_priority(seeded: sessionmaker[Session]) -> None:
    """D§17."""
    with seeded() as session:
        targets = (
            session.execute(
                select(Product.slug)
                .join(
                    ProductRelationship,
                    ProductRelationship.target_product_id == Product.id,
                )
                .where(
                    ProductRelationship.source_product_id == seed_id("product", "aerocase_pro"),
                    ProductRelationship.relationship_type == "cross_sell",
                )
                .order_by(ProductRelationship.priority)
            )
            .scalars()
            .all()
        )

    assert targets == ["guardglass_2_5d", "voltedge_30w"]


def test_available_quantity_is_quantity_minus_reserved(
    seeded: sessionmaker[Session],
) -> None:
    """D§11."""
    with seeded() as session:
        inventory = session.get(Inventory, seed_id("inventory", "CASE-IP16-BLK"))

    assert inventory is not None
    assert inventory.quantity == 20
    assert inventory.reserved_quantity == 0
    assert inventory.available_quantity == 20


# --------------------------------------------------------------------------
# Constraints actually reject
# --------------------------------------------------------------------------


def _expect_integrity_error(session: Session, constraint: str) -> None:
    with pytest.raises(IntegrityError) as exc_info:
        session.flush()
    assert constraint in str(exc_info.value)
    session.rollback()


def test_duplicate_sku_within_a_merchant_is_rejected(session: Session) -> None:
    """D§23."""
    session.add(
        ProductVariant(
            merchant_id=DEFAULT_MERCHANT_ID,
            product_id=seed_id("product", "aerocase_pro"),
            sku="CASE-IP16-BLK",
            name="Duplicate",
            price=Decimal("1.00"),
            currency="INR",
        )
    )
    _expect_integrity_error(session, "uq_product_variants_merchant_id_sku")


def test_duplicate_category_slug_within_a_merchant_is_rejected(session: Session) -> None:
    session.add(Category(merchant_id=DEFAULT_MERCHANT_ID, name="Duplicate", slug="phone_case"))
    _expect_integrity_error(session, "uq_categories_merchant_id_slug")


def test_a_second_inventory_row_for_one_variant_is_rejected(session: Session) -> None:
    """D§11: one inventory record per variant."""
    session.add(Inventory(variant_id=seed_id("variant", "CASE-IP16-BLK"), quantity=1))
    _expect_integrity_error(session, "uq_inventory_variant_id")


def test_a_variant_for_a_nonexistent_product_is_rejected(session: Session) -> None:
    """D§22: foreign keys prevent orphans."""
    session.add(
        ProductVariant(
            merchant_id=DEFAULT_MERCHANT_ID,
            product_id=seed_id("product", "does_not_exist"),
            sku="GHOST-1",
            name="Ghost",
            price=Decimal("1.00"),
            currency="INR",
        )
    )
    _expect_integrity_error(session, "fk_product_variants")


def test_a_negative_price_is_rejected(session: Session) -> None:
    session.add(
        ProductVariant(
            merchant_id=DEFAULT_MERCHANT_ID,
            product_id=seed_id("product", "aerocase_pro"),
            sku="NEGATIVE-1",
            name="Negative",
            price=Decimal("-1.00"),
            currency="INR",
        )
    )
    _expect_integrity_error(session, "ck_product_variants_price_is_not_negative")


def test_a_lowercase_sku_is_rejected(session: Session) -> None:
    session.add(
        ProductVariant(
            merchant_id=DEFAULT_MERCHANT_ID,
            product_id=seed_id("product", "aerocase_pro"),
            sku="lowercase-sku",
            name="Lowercase",
            price=Decimal("1.00"),
            currency="INR",
        )
    )
    _expect_integrity_error(session, "ck_product_variants_sku_is_uppercase_token")


def test_reserving_more_than_exists_is_rejected(session: Session) -> None:
    """D§11: available quantity cannot go negative."""
    inventory = session.get(Inventory, seed_id("inventory", "CASE-IP16-BLK"))
    assert inventory is not None
    inventory.reserved_quantity = inventory.quantity + 1
    _expect_integrity_error(session, "ck_inventory_reserved_quantity_within_quantity")


def test_a_non_canonical_compatibility_identifier_is_rejected(session: Session) -> None:
    """ADR-003: a resolution bug cannot write an unmatchable row."""
    session.add(
        CompatibilityRule(
            product_id=seed_id("product", "aerocase_pro"),
            target_type="phone_model",
            target_identifier="iPhone 16",
            rule_type="compatible",
        )
    )
    _expect_integrity_error(session, "ck_compatibility_rules_target_identifier_is_canonical_token")


def test_an_unsupported_rule_type_is_rejected(session: Session) -> None:
    """ADR-003: only 'compatible' in the MVP."""
    session.add(
        CompatibilityRule(
            product_id=seed_id("product", "aerocase_pro"),
            target_type="phone_model",
            target_identifier="pixel_9",
            rule_type="incompatible",
        )
    )
    _expect_integrity_error(session, "ck_compatibility_rules_rule_type_is_supported")


def test_an_unknown_relationship_type_is_rejected(session: Session) -> None:
    session.add(
        ProductRelationship(
            source_product_id=seed_id("product", "aerocase_pro"),
            target_product_id=seed_id("product", "sonicbuds_air"),
            relationship_type="upsell",
        )
    )
    _expect_integrity_error(session, "ck_product_relationships_relationship_type_is_known")


def test_a_product_cannot_relate_to_itself(session: Session) -> None:
    session.add(
        ProductRelationship(
            source_product_id=seed_id("product", "aerocase_pro"),
            target_product_id=seed_id("product", "aerocase_pro"),
            relationship_type="related",
        )
    )
    _expect_integrity_error(session, "ck_product_relationships_source_differs_from_target")


def test_a_category_cannot_be_its_own_parent(session: Session) -> None:
    category = session.get(Category, seed_id("category", "phone_case"))
    assert category is not None
    category.parent_id = category.id
    _expect_integrity_error(session, "ck_categories_parent_is_not_self")


def test_a_product_cannot_use_another_merchants_category(session: Session) -> None:
    """ADR-002: merchant scoping is an invariant, not a convention."""
    other_merchant = seed_id("merchant", "other")
    session.add(Merchant(id=other_merchant, name="Other Merchant", currency="INR"))
    session.flush()

    session.add(
        Product(
            merchant_id=other_merchant,
            # A CircuitCraft category.
            category_id=seed_id("category", "phone_case"),
            name="Trespasser",
            slug="trespasser",
        )
    )
    _expect_integrity_error(session, "fk_products_category_within_merchant")


def test_attributes_must_be_a_json_object(session: Session) -> None:
    """JSONB accepts arrays and scalars; the schema does not (D§7).

    Raw SQL rather than the ORM, because the ORM would serialise a Python list
    into a JSON array anyway and this asserts the database's own guard. The
    error surfaces at execute time rather than at flush, so it is caught here
    directly.
    """
    statement = text(
        "INSERT INTO products (merchant_id, category_id, name, slug, attributes) "
        "VALUES (:m, :c, 'Bad', 'bad_attributes', '[1,2,3]'::jsonb)"
    ).bindparams(m=DEFAULT_MERCHANT_ID, c=seed_id("category", "phone_case"))

    with pytest.raises(IntegrityError) as exc_info:
        session.execute(statement)

    assert "ck_products_attributes_is_object" in str(exc_info.value)
    session.rollback()
