"""Load the CircuitCraft catalog into PostgreSQL.

    python -m app.seed.circuitcraft                 validate, then load
    python -m app.seed.circuitcraft --validate-only validate only; no database
    python -m app.seed.circuitcraft --summary       what is in the database now

Loading is **idempotent**. Every row's primary key is a UUIDv5 derived from its
natural key — merchant name, category slug, product slug, SKU — so running the
loader twice addresses the same rows rather than inserting a second catalog
(``app.identifiers``; ADR-002).

The file is fully validated before a single statement is issued, so a malformed
catalog fails with a message naming the offending row rather than as a
constraint violation halfway through a transaction.
"""

from __future__ import annotations

import argparse
import logging
import sys
import uuid
from collections.abc import Sequence

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import get_settings
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
from app.db.session import get_sessionmaker
from app.identifiers import seed_id
from app.logging_config import configure_logging
from app.seed.schema import CatalogSeed, load_catalog

logger = logging.getLogger(__name__)


def seed_catalog(session: Session, catalog: CatalogSeed, merchant_id: uuid.UUID) -> dict[str, int]:
    """Write the catalog. Returns a count per table.

    Uses ``Session.merge`` throughout: it looks the row up by primary key and
    either inserts or updates, which is what makes re-running safe.
    """
    counts = {
        "merchants": 0,
        "categories": 0,
        "products": 0,
        "product_variants": 0,
        "inventory": 0,
        "compatibility_rules": 0,
        "product_relationships": 0,
        "compatibility_targets": 0,
    }
    currency = catalog.merchant.currency

    session.merge(
        Merchant(
            id=merchant_id,
            name=catalog.merchant.name,
            description=catalog.merchant.description,
            currency=currency,
            is_active=True,
        )
    )
    counts["merchants"] += 1

    # Parents before children, so a self-referencing foreign key is always
    # satisfied at flush time.
    for category in _categories_parents_first(catalog):
        session.merge(
            Category(
                id=seed_id("category", category.slug),
                merchant_id=merchant_id,
                name=category.name,
                slug=category.slug,
                parent_id=(seed_id("category", category.parent) if category.parent else None),
            )
        )
        counts["categories"] += 1
        # Flushed per row, not once at the end. `_categories_parents_first`
        # guarantees the order, but the unit of work is free to emit an UPDATE
        # to an existing child before the INSERT of its new parent — which is
        # exactly what happens when a category is re-parented into a branch that
        # does not exist yet, and `fk_categories_parent_id_categories` rejects it.
        session.flush()

    for target in catalog.compatibility_targets:
        session.merge(
            CompatibilityTarget(
                id=seed_id(
                    "compatibility_target",
                    f"{target.target_type}:{target.canonical_identifier}",
                ),
                target_type=target.target_type,
                canonical_identifier=target.canonical_identifier,
                display_name=target.display_name,
                aliases=list(target.aliases),
                is_active=True,
            )
        )
        counts["compatibility_targets"] += 1

    for product in catalog.products:
        product_id = seed_id("product", product.slug)
        session.merge(
            Product(
                id=product_id,
                merchant_id=merchant_id,
                category_id=seed_id("category", product.category),
                name=product.name,
                slug=product.slug,
                description=product.description,
                brand=product.brand,
                attributes=dict(product.attributes),
                tags=list(product.tags),
                is_active=True,
            )
        )
        counts["products"] += 1
        session.flush()

        for variant in product.variants:
            variant_id = seed_id("variant", variant.sku)
            session.merge(
                ProductVariant(
                    id=variant_id,
                    merchant_id=merchant_id,
                    product_id=product_id,
                    sku=variant.sku,
                    name=variant.name,
                    price=variant.price,
                    currency=currency,
                    attributes=dict(variant.attributes),
                    is_active=True,
                )
            )
            counts["product_variants"] += 1
            session.flush()

            session.merge(
                Inventory(
                    id=seed_id("inventory", variant.sku),
                    variant_id=variant_id,
                    quantity=variant.quantity,
                    # ADR-005: no reservation mechanism in the MVP.
                    reserved_quantity=0,
                )
            )
            counts["inventory"] += 1

        for rule in product.compatibility:
            session.merge(
                CompatibilityRule(
                    id=seed_id(
                        "compatibility_rule",
                        f"{product.slug}:{rule.target_type}:{rule.target_identifier}",
                    ),
                    product_id=product_id,
                    target_type=rule.target_type,
                    target_identifier=rule.target_identifier,
                    rule_type="compatible",
                    constraints=dict(rule.constraints),
                )
            )
            counts["compatibility_rules"] += 1

    session.flush()

    for rel in catalog.relationships:
        session.merge(
            ProductRelationship(
                id=seed_id("relationship", f"{rel.source}:{rel.target}:{rel.type}"),
                source_product_id=seed_id("product", rel.source),
                target_product_id=seed_id("product", rel.target),
                relationship_type=rel.type,
                priority=rel.priority,
            )
        )
        counts["product_relationships"] += 1

    session.flush()
    return counts


def prune_catalog(session: Session, catalog: CatalogSeed, merchant_id: uuid.UUID) -> dict[str, int]:
    """Remove merchant rows the seed file no longer contains.

    Seeding is an upsert and never deletes, which is right for a loader: a
    merchant may legitimately add products through the dashboard, and a loader
    that silently removed them would be a data-loss bug. So pruning is a
    separate, explicit request — it is how a *category* is retired, and it is
    the only way to take a product out of the catalogue wholesale.

    **Order history is never destroyed.** A variant somebody has bought or has
    in a cart is deactivated and zeroed rather than deleted: `order_items` and
    `cart_items` reference it, and an order that cannot name what was sold is
    worse than a catalogue with a hidden row in it. Everything unreferenced is
    deleted outright, and a category is deleted once nothing points at it —
    `categories` has no `is_active`, so for a category there is no third option.
    """
    from sqlalchemy import delete, exists, or_, update

    from app.db.models import CartItem, OrderItem

    counts = {
        "products_deleted": 0,
        "products_deactivated": 0,
        "variants_deleted": 0,
        "variants_deactivated": 0,
        "categories_deleted": 0,
        "relationships_deleted": 0,
        "compatibility_rules_deleted": 0,
    }

    keep_products = {seed_id("product", product.slug) for product in catalog.products}
    keep_categories = {seed_id("category", category.slug) for category in catalog.categories}

    stale_products = (
        session.execute(
            select(Product).where(
                Product.merchant_id == merchant_id, Product.id.not_in(keep_products)
            )
        )
        .scalars()
        .all()
    )
    stale_ids = [product.id for product in stale_products]

    if stale_ids:
        counts["relationships_deleted"] = session.execute(
            delete(ProductRelationship).where(
                or_(
                    ProductRelationship.source_product_id.in_(stale_ids),
                    ProductRelationship.target_product_id.in_(stale_ids),
                )
            )
        ).rowcount
        counts["compatibility_rules_deleted"] = session.execute(
            delete(CompatibilityRule).where(CompatibilityRule.product_id.in_(stale_ids))
        ).rowcount

        for product in stale_products:
            variants = (
                session.execute(
                    select(ProductVariant).where(ProductVariant.product_id == product.id)
                )
                .scalars()
                .all()
            )
            kept_any = False
            for variant in variants:
                referenced = session.execute(
                    select(
                        exists().where(OrderItem.variant_id == variant.id)
                        | exists().where(CartItem.variant_id == variant.id)
                    )
                ).scalar_one()
                if referenced:
                    variant.is_active = False
                    session.execute(
                        update(Inventory)
                        .where(Inventory.variant_id == variant.id)
                        .values(quantity=0, reserved_quantity=0)
                    )
                    counts["variants_deactivated"] += 1
                    kept_any = True
                else:
                    session.execute(delete(Inventory).where(Inventory.variant_id == variant.id))
                    session.delete(variant)
                    counts["variants_deleted"] += 1
            session.flush()
            if kept_any:
                product.is_active = False
                counts["products_deactivated"] += 1
            else:
                session.delete(product)
                counts["products_deleted"] += 1
        session.flush()

    # Categories last: a category can only go once nothing points at it, and
    # children before parents for the same reason.
    for _ in range(len(catalog.categories) + 1):
        removable = (
            session.execute(
                select(Category).where(
                    Category.merchant_id == merchant_id,
                    Category.id.not_in(keep_categories),
                    ~exists().where(Product.category_id == Category.id),
                    ~exists().where(Category.id == Category.__table__.c.parent_id),
                )
            )
            .scalars()
            .all()
        )
        if not removable:
            break
        for category in removable:
            session.delete(category)
            counts["categories_deleted"] += 1
        session.flush()

    return counts


def _categories_parents_first(catalog: CatalogSeed) -> list:
    """Order categories so every parent precedes its children."""
    by_slug = {category.slug: category for category in catalog.categories}
    ordered: list = []
    placed: set[str] = set()

    def place(slug: str) -> None:
        if slug in placed:
            return
        category = by_slug[slug]
        if category.parent:
            place(category.parent)
        placed.add(slug)
        ordered.append(category)

    for category in catalog.categories:
        place(category.slug)
    return ordered


def database_summary(session: Session) -> dict[str, int]:
    """Row counts per catalog table."""
    models = {
        "merchants": Merchant,
        "categories": Category,
        "products": Product,
        "product_variants": ProductVariant,
        "inventory": Inventory,
        "compatibility_rules": CompatibilityRule,
        "product_relationships": ProductRelationship,
        "compatibility_targets": CompatibilityTarget,
    }
    return {
        name: session.execute(select(func.count()).select_from(model)).scalar_one()
        for name, model in models.items()
    }


def _report(title: str, counts: dict[str, int]) -> None:
    print(title)
    for name, count in counts.items():
        print(f"  {name:<24} {count:>5}")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Load the CircuitCraft catalog.")
    parser.add_argument(
        "--validate-only",
        action="store_true",
        help="validate the seed file and exit; touches no database",
    )
    parser.add_argument(
        "--prune",
        action="store_true",
        help=(
            "after loading, remove merchant rows the seed file no longer contains. "
            "Rows an order or a cart references are deactivated instead of deleted."
        ),
    )
    parser.add_argument(
        "--summary",
        action="store_true",
        help="print catalog row counts from the database and exit",
    )
    args = parser.parse_args(argv)

    settings = get_settings()
    configure_logging(
        level=settings.log_level, fmt=settings.log_format, secrets=settings.secret_values()
    )

    try:
        catalog = load_catalog()
    except Exception as exc:
        print(f"Seed catalog is invalid:\n\n{exc}", file=sys.stderr)
        return 1

    print(
        f"Seed file valid: {len(catalog.products)} products, "
        f"{catalog.variant_count} SKUs, "
        f"{len(catalog.categories)} categories, "
        f"{catalog.rule_count} compatibility rules, "
        f"{len(catalog.compatibility_targets)} compatibility targets, "
        f"{len(catalog.relationships)} relationships."
    )
    if args.validate_only:
        return 0

    session_factory = get_sessionmaker()

    if args.summary:
        with session_factory() as session:
            _report("Catalog rows currently in the database:", database_summary(session))
        return 0

    with session_factory() as session, session.begin():
        counts = seed_catalog(session, catalog, settings.default_merchant_id)
        pruned = (
            prune_catalog(session, catalog, settings.default_merchant_id) if args.prune else None
        )
    _report("Seeded (idempotent - re-running updates the same rows):", counts)
    if pruned is not None:
        _report("Pruned (rows the seed file no longer contains):", pruned)

    logger.info("catalog seeded", extra={"merchant_id": str(settings.default_merchant_id)})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
