"""The CircuitCraft seed catalog, validated as data.

None of this needs a database. The catalog is the authoritative source of
product facts (ADR-002), so its integrity is worth asserting directly rather
than inferring from whether an INSERT happened to succeed.

Three groups:

* **Integrity** — referential closure, uniqueness, canonical tokens, money as
  ``Decimal``.
* **Fidelity** — the handful of values architecture.md actually supplies are
  reproduced exactly.
* **Testability** — the catalog contains the shapes M2 and M3 will need in order
  to test each hard constraint separately.
"""

from __future__ import annotations

import json
from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.canonical import is_canonical_token, normalize_token
from app.db.models import (
    COMPATIBILITY_TARGET_KINDS,
    COMPATIBILITY_TARGET_TYPES,
    PRODUCT_RELATIONSHIP_TYPES,
)
from app.seed.schema import CATALOG_PATH, CatalogSeed, load_catalog


@pytest.fixture(scope="module")
def catalog() -> CatalogSeed:
    return load_catalog()


@pytest.fixture(scope="module")
def raw_catalog() -> dict:
    return json.loads(CATALOG_PATH.read_text(encoding="utf-8"))


# --------------------------------------------------------------------------
# Integrity
# --------------------------------------------------------------------------


def test_the_shipped_catalog_validates(catalog: CatalogSeed) -> None:
    assert catalog.merchant.name == "EASY BUY"
    assert catalog.merchant.currency == "INR"


def test_the_catalog_is_an_electronics_only_storefront(catalog: CatalogSeed) -> None:
    """ADR-021, as narrowed on 2026-09-05 at the owner's request (deviation D13).

    The catalogue was grown past R§18's 30-36 SKU prototype scope into
    electronics *plus clothing and furniture*; it has since been narrowed back
    to a focused consumer-electronics store and grown much larger within that
    scope. The original electronics rows are preserved unchanged - see
    ``test_the_original_electronics_prototype_is_preserved`` below.

    The assertion that matters is the **negative** one: every category descends
    from ``electronics``. A catalogue that quietly regained a clothing branch
    would still pass every count.
    """
    assert catalog.variant_count >= 300
    by_slug = {c.slug: c for c in catalog.categories}

    def root(slug: str) -> str:
        while by_slug[slug].parent:
            slug = by_slug[slug].parent
        return slug

    roots = {root(c.slug) for c in catalog.categories}
    assert roots == {"electronics"}, f"non-electronics families present: {roots - {'electronics'}}"
    assert {"smartphone", "laptop", "phone_case", "earbuds"} <= set(by_slug)


def test_the_original_electronics_prototype_is_preserved(catalog: CatalogSeed) -> None:
    """The architecture.md worked-example rows must never be edited (ADR-021)."""
    variants = {v.sku: v for p in catalog.products for v in p.variants}
    assert variants["CASE-IP16-BLK"].price == Decimal("999.00")  # D§34
    assert variants["CHARGER-30W"].price == Decimal("1499.00")  # L§20-21
    assert variants["SPRO-IP16-1"].price == Decimal("299.00")  # L§25
    shield = next(p for p in catalog.products if p.slug == "shieldcase_premium")
    assert shield.variants[0].price == Decimal("1299.00")  # R§10
    assert shield.variants[0].quantity == 5  # R§10


def test_every_sku_is_unique_across_the_merchant(catalog: CatalogSeed) -> None:
    """D§10, D§23: UNIQUE(merchant_id, sku)."""
    skus = [v.sku for p in catalog.products for v in p.variants]
    assert len(skus) == len(set(skus))


def test_every_product_and_category_slug_is_unique_and_canonical(
    catalog: CatalogSeed,
) -> None:
    product_slugs = [p.slug for p in catalog.products]
    category_slugs = [c.slug for c in catalog.categories]

    assert len(product_slugs) == len(set(product_slugs))
    assert len(category_slugs) == len(set(category_slugs))
    for slug in (*product_slugs, *category_slugs):
        assert is_canonical_token(slug), slug


def test_every_product_resolves_to_a_seeded_category(catalog: CatalogSeed) -> None:
    known = {c.slug for c in catalog.categories}
    for product in catalog.products:
        assert product.category in known


def test_every_relationship_resolves_to_seeded_products(catalog: CatalogSeed) -> None:
    known = {p.slug for p in catalog.products}
    for rel in catalog.relationships:
        assert rel.source in known and rel.target in known
        assert rel.source != rel.target
        assert rel.type in PRODUCT_RELATIONSHIP_TYPES


def test_every_compatibility_identifier_resolves_to_a_seeded_target(
    catalog: CatalogSeed,
) -> None:
    """ADR-003.

    Not enforceable as a foreign key — a rule's target_type and a target's
    target_type are different axes — so it is enforced here and in the service
    layer.
    """
    known = {t.canonical_identifier for t in catalog.compatibility_targets}
    for product in catalog.products:
        for rule in product.compatibility:
            assert rule.target_identifier in known, (product.slug, rule.target_identifier)
            assert rule.target_type in COMPATIBILITY_TARGET_TYPES


def test_every_compatibility_target_kind_is_one_the_database_permits(
    catalog: CatalogSeed,
) -> None:
    for target in catalog.compatibility_targets:
        assert target.target_type in COMPATIBILITY_TARGET_KINDS


def test_every_alias_is_already_normalized(catalog: CatalogSeed) -> None:
    """An unnormalized alias can never match, and fails silently."""
    for target in catalog.compatibility_targets:
        for alias in target.aliases:
            assert alias == normalize_token(alias), (target.canonical_identifier, alias)


def test_no_token_resolves_to_two_different_targets(catalog: CatalogSeed) -> None:
    """Ambiguity must be impossible, not merely unlikely (ADR-003)."""
    owner: dict[str, str] = {}
    for target in catalog.compatibility_targets:
        for token in (target.canonical_identifier, *target.aliases):
            key = f"{target.target_type}:{target.canonical_identifier}"
            assert owner.get(token, key) == key, token
            owner[token] = key


# --------------------------------------------------------------------------
# Money (ADR-008)
# --------------------------------------------------------------------------


def test_every_price_is_a_decimal_with_at_most_two_places(catalog: CatalogSeed) -> None:
    for product in catalog.products:
        for variant in product.variants:
            assert isinstance(variant.price, Decimal)
            assert variant.price >= 0
            assert -variant.price.as_tuple().exponent <= 2


def test_no_price_in_the_json_file_is_a_number(raw_catalog: dict) -> None:
    """ADR-008: json.loads turns 999.00 into a float before validation runs."""
    for product in raw_catalog["products"]:
        for variant in product["variants"]:
            assert isinstance(variant["price"], str), (
                f"{variant['sku']} price must be a JSON string, not a number"
            )


def test_a_numeric_price_is_rejected() -> None:
    """The guard, exercised."""
    with pytest.raises(ValidationError, match="must be a JSON string"):
        CatalogSeed.model_validate(
            {
                "merchant": {"name": "X", "currency": "INR"},
                "categories": [{"slug": "c", "name": "C", "parent": None}],
                "products": [
                    {
                        "slug": "p",
                        "name": "P",
                        "category": "c",
                        "variants": [{"sku": "SKU-1", "name": "V", "price": 999.0, "quantity": 1}],
                    }
                ],
            }
        )


# --------------------------------------------------------------------------
# Fidelity to the values architecture.md actually supplies
# --------------------------------------------------------------------------


def variant(catalog: CatalogSeed, sku: str):
    for product in catalog.products:
        for candidate in product.variants:
            if candidate.sku == sku:
                return product, candidate
    raise AssertionError(f"{sku} is not in the catalog")


def test_the_one_complete_record_the_specification_gives_is_reproduced(
    catalog: CatalogSeed,
) -> None:
    """architecture.md D§34."""
    product, sku = variant(catalog, "CASE-IP16-BLK")

    assert product.name == "AeroCase Pro"
    assert product.category == "phone_case"
    assert product.description == "Slim protective case for compatible smartphones."
    assert product.attributes["material"] == "TPU"
    assert set(product.tags) >= {"iphone", "protective", "slim"}
    assert sku.price == Decimal("999.00")
    assert sku.quantity == 20

    assert any(
        rule.target_type == "phone_model" and rule.target_identifier == "iphone_16"
        for rule in product.compatibility
    )
    assert any(
        rel.source == "aerocase_pro"
        and rel.target == "guardglass_2_5d"
        and rel.type == "cross_sell"
        for rel in catalog.relationships
    )


def test_prices_named_in_worked_examples_are_reproduced(catalog: CatalogSeed) -> None:
    """R§10 (1299, stock 5), L§21 (30W charger 1499), L§25 (protector 299)."""
    _, shieldcase = variant(catalog, "CASE-IP16-SHD-BLK")
    assert shieldcase.price == Decimal("1299.00")
    assert shieldcase.quantity == 5

    _, charger = variant(catalog, "CHARGER-30W")
    assert charger.price == Decimal("1499.00")

    _, protector = variant(catalog, "SPRO-IP16-1")
    assert protector.price == Decimal("299.00")


def test_the_charger_constraint_example_is_reproduced_verbatim(
    catalog: CatalogSeed,
) -> None:
    """D§14, read as predicates on the product's own attributes (ADR-003/B3)."""
    charger = next(p for p in catalog.products if p.slug == "voltedge_30w")
    rule = next(r for r in charger.compatibility if r.target_identifier == "iphone_16")

    assert rule.target_type == "device"
    assert rule.constraints == {"minimum_wattage": 20, "fast_charge": True}

    # The predicates must actually hold for this product, or the rule is a lie.
    assert charger.attributes["wattage"] >= rule.constraints["minimum_wattage"]
    assert charger.attributes["fast_charge"] is True


def test_every_constraint_predicate_is_satisfied_by_its_own_product(
    catalog: CatalogSeed,
) -> None:
    """ADR-003/B3 applied to the whole catalog, not just the example."""
    for product in catalog.products:
        for rule in product.compatibility:
            for key, expected in rule.constraints.items():
                if key.startswith("minimum_"):
                    attribute = key.removeprefix("minimum_")
                    assert product.attributes[attribute] >= expected, (product.slug, key)
                else:
                    assert product.attributes[key] == expected, (product.slug, key)


def test_the_specified_category_names_are_present(catalog: CatalogSeed) -> None:
    """D§5 lists CircuitCraft's categories."""
    names = {c.name for c in catalog.categories}
    assert {
        "Phone Cases",
        "USB Cables",
        "Power Banks",
        "Earbuds",
        "Screen Protectors",
        "Laptop Sleeves",
    } <= names
    assert any(name.startswith("Chargers") for name in names)


def test_the_category_hierarchy_matches_the_documented_example(
    catalog: CatalogSeed,
) -> None:
    """D§5: Electronics → Mobile Accessories → Phone Cases."""
    by_slug = {c.slug: c for c in catalog.categories}

    assert by_slug["electronics"].parent is None
    assert by_slug["mobile_accessories"].parent == "electronics"
    assert by_slug["phone_case"].parent == "mobile_accessories"
    assert by_slug["laptop_accessories"].parent == "electronics"
    assert by_slug["laptop_sleeve"].parent == "laptop_accessories"


# --------------------------------------------------------------------------
# Shapes the later milestones need in order to test each filter separately
# --------------------------------------------------------------------------


def test_catalog_contains_an_out_of_stock_variant(catalog: CatalogSeed) -> None:
    """ADR-005: inventory eliminates, it does not merely demote."""
    zero = [v.sku for p in catalog.products for v in p.variants if v.quantity == 0]
    assert zero, "no out-of-stock SKU: the inventory filter would be untestable"


def test_catalog_contains_a_case_for_the_previous_phone(catalog: CatalogSeed) -> None:
    """ADR-005: an iPhone 15 case must be excluded from an iPhone 16 search."""
    iphone_15_cases = [
        p.slug
        for p in catalog.products
        if p.category == "phone_case"
        and any(r.target_identifier == "iphone_15" for r in p.compatibility)
    ]
    assert iphone_15_cases


def test_catalog_straddles_the_budget_line_used_in_the_examples(
    catalog: CatalogSeed,
) -> None:
    """The worked example is "a case under ₹1,500"."""
    case_prices = [
        v.price for p in catalog.products if p.category == "phone_case" for v in p.variants
    ]
    assert any(price <= Decimal("1500") for price in case_prices)
    assert any(price > Decimal("1500") for price in case_prices)


def test_a_resolvable_device_exists_with_no_compatible_products(
    catalog: CatalogSeed,
) -> None:
    """R§14: "Case for Pixel 9?" is a no-match, not a failed lookup.

    Distinguishing the two is the whole point of ADR-003, so the catalog has to
    contain an example of each.
    """
    assert any(t.canonical_identifier == "pixel_9" for t in catalog.compatibility_targets)

    compatible = [
        p.slug
        for p in catalog.products
        if any(r.target_identifier == "pixel_9" for r in p.compatibility)
    ]
    assert compatible == []


def test_some_products_have_no_compatibility_requirement_at_all(
    catalog: CatalogSeed,
) -> None:
    """Earbuds are universal; the filter must handle an absent requirement."""
    unconstrained = [p.slug for p in catalog.products if not p.compatibility]
    assert unconstrained


def test_multi_variant_products_exist_alongside_single_variant_ones(
    catalog: CatalogSeed,
) -> None:
    """D§9: both shapes are normal, and both must be handled."""
    counts = {len(p.variants) for p in catalog.products}
    assert 1 in counts
    assert max(counts) > 1


def test_cross_sell_and_bundle_relationships_both_exist(catalog: CatalogSeed) -> None:
    """D§17."""
    kinds = {rel.type for rel in catalog.relationships}
    assert {"cross_sell", "bundle"} <= kinds


# --------------------------------------------------------------------------
# The validator itself
# --------------------------------------------------------------------------


def _minimal() -> dict:
    return {
        "merchant": {"name": "X", "currency": "INR"},
        "categories": [{"slug": "c", "name": "C", "parent": None}],
        "compatibility_targets": [
            {
                "target_type": "phone_model",
                "canonical_identifier": "iphone_16",
                "display_name": "iPhone 16",
                "aliases": [],
            }
        ],
        "products": [
            {
                "slug": "p",
                "name": "P",
                "category": "c",
                "variants": [{"sku": "SKU-1", "name": "V", "price": "1.00", "quantity": 1}],
                "compatibility": [{"target_type": "phone_model", "target_identifier": "iphone_16"}],
            }
        ],
        "relationships": [],
    }


def test_minimal_catalog_is_accepted() -> None:
    assert CatalogSeed.model_validate(_minimal())


@pytest.mark.parametrize(
    ("mutate", "expected"),
    [
        pytest.param(
            lambda d: d["products"][0].update(category="missing"),
            "unknown category",
            id="unknown-category",
        ),
        pytest.param(
            lambda d: d["products"][0]["compatibility"].append(
                {"target_type": "phone_model", "target_identifier": "pixel_9"}
            ),
            "unknown target",
            id="unknown-compatibility-target",
        ),
        pytest.param(
            lambda d: d["categories"].append({"slug": "c", "name": "Dup", "parent": None}),
            "duplicate category slug",
            id="duplicate-category",
        ),
        pytest.param(
            lambda d: d["products"][0]["variants"].append(
                {"sku": "SKU-1", "name": "V2", "price": "2.00", "quantity": 1}
            ),
            "repeats a SKU",
            id="duplicate-sku",
        ),
        pytest.param(
            lambda d: d["categories"][0].update(parent="c"),
            "cycle",
            id="category-cycle",
        ),
        pytest.param(
            lambda d: d["products"][0]["variants"][0].update(sku="lowercase-sku"),
            "uppercase",
            id="lowercase-sku",
        ),
        pytest.param(
            lambda d: d["products"][0].update(slug="Not A Token"),
            "canonical token",
            id="non-canonical-slug",
        ),
        pytest.param(
            lambda d: d["compatibility_targets"][0].update(aliases=["iPhone 16"]),
            "not normalized",
            id="unnormalized-alias",
        ),
        pytest.param(
            lambda d: d["products"][0]["variants"][0].update(quantity=-1),
            "greater than or equal to 0",
            id="negative-quantity",
        ),
        pytest.param(
            lambda d: d["products"][0]["variants"][0].update(price="1.005"),
            "two decimal places",
            id="over-precise-price",
        ),
        pytest.param(
            lambda d: d["relationships"].append({"source": "p", "target": "p", "type": "related"}),
            "points at itself",
            id="self-relationship",
        ),
        pytest.param(
            lambda d: d["relationships"].append(
                {"source": "p", "target": "gone", "type": "related"}
            ),
            "unknown product",
            id="dangling-relationship",
        ),
    ],
)
def test_invalid_catalogs_are_rejected_with_a_useful_message(mutate, expected: str) -> None:
    data = _minimal()
    mutate(data)

    with pytest.raises(ValidationError) as exc_info:
        CatalogSeed.model_validate(data)

    assert expected in str(exc_info.value)
