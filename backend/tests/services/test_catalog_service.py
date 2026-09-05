"""CatalogService — authoritative product retrieval.

The property under test throughout is the pre-submission gate item PG-2: the
catalog cannot produce a SKU, a price or a product that is not in the database.
Several tests therefore assert what the service *refuses* to return, which is
the half that actually enforces the rule.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from sqlalchemy.orm import Session

from app.db.models import Category, Merchant, Product, ProductVariant
from app.domain import ProductDetail, VariantView
from app.services import CatalogService
from app.services.catalog_service import VariantQuery
from tests.services.conftest import OTHER_MERCHANT_ID

pytestmark = pytest.mark.requires_db


# --------------------------------------------------------------------------
# 1. Product lookup
# --------------------------------------------------------------------------


def test_get_product_returns_the_product_and_all_its_variants(
    catalog: CatalogService, merchant_id: uuid.UUID, product_id
) -> None:
    detail = catalog.get_product(merchant_id, product_id("aerocase_pro"))

    assert isinstance(detail, ProductDetail)
    assert detail.product.slug == "aerocase_pro"
    assert detail.product.name == "AeroCase Pro"
    assert detail.product.category_slug == "phone_case"
    assert {v.sku for v in detail.variants} == {
        "CASE-IP16-BLK",
        "CASE-IP16-BLU",
        "CASE-IP16-CLR",
    }


def test_get_product_by_slug_agrees_with_get_product(
    catalog: CatalogService, merchant_id: uuid.UUID, product_id
) -> None:
    by_id = catalog.get_product(merchant_id, product_id("shieldcase_premium"))
    by_slug = catalog.get_product_by_slug(merchant_id, "shieldcase_premium")

    assert by_id is not None and by_slug is not None
    assert by_id.product == by_slug.product


def test_unknown_product_returns_none_rather_than_anything_invented(
    catalog: CatalogService, merchant_id: uuid.UUID
) -> None:
    assert catalog.get_product(merchant_id, uuid.uuid4()) is None
    assert catalog.get_product_by_slug(merchant_id, "no_such_product") is None


def test_service_returns_domain_types_not_orm_rows(
    catalog: CatalogService, merchant_id: uuid.UUID, variant_id
) -> None:
    """A live ORM row would let callers emit queries from anywhere."""
    variant = catalog.get_variant(merchant_id, variant_id("CASE-IP16-BLK"))

    assert isinstance(variant, VariantView)
    assert not isinstance(variant, ProductVariant)
    with pytest.raises((AttributeError, TypeError)):
        variant.price = Decimal("1.00")  # type: ignore[misc]


# --------------------------------------------------------------------------
# 2. Merchant scoping
# --------------------------------------------------------------------------


def test_another_merchant_cannot_read_this_catalog(
    catalog: CatalogService, variant_id, product_id
) -> None:
    """Scoping must exclude, not merely order.

    The rows exist; a query that forgot `merchant_id` would return them.
    """
    assert catalog.get_product(OTHER_MERCHANT_ID, product_id("aerocase_pro")) is None
    assert catalog.get_variant(OTHER_MERCHANT_ID, variant_id("CASE-IP16-BLK")) is None
    assert catalog.get_variant_by_sku(OTHER_MERCHANT_ID, "CASE-IP16-BLK") is None
    assert catalog.search(OTHER_MERCHANT_ID, VariantQuery()) == []
    assert catalog.list_categories(OTHER_MERCHANT_ID) == []


def test_a_second_merchant_reusing_a_sku_does_not_collide(
    session: Session, catalog: CatalogService, merchant_id: uuid.UUID
) -> None:
    """D§10: SKU is unique per merchant, not globally.

    Two merchants may hold the same SKU string, and a lookup must return each
    one's own product.
    """
    session.add(Merchant(id=OTHER_MERCHANT_ID, name="Probe Merchant", currency="INR"))
    session.flush()
    other_category = Category(merchant_id=OTHER_MERCHANT_ID, name="Cases", slug="phone_case")
    session.add(other_category)
    session.flush()
    other_product = Product(
        merchant_id=OTHER_MERCHANT_ID,
        category_id=other_category.id,
        name="Impostor Case",
        slug="impostor_case",
    )
    session.add(other_product)
    session.flush()
    session.add(
        ProductVariant(
            merchant_id=OTHER_MERCHANT_ID,
            product_id=other_product.id,
            sku="CASE-IP16-BLK",  # the same SKU CircuitCraft uses
            name="Black",
            price=Decimal("1.00"),
            currency="INR",
        )
    )
    session.flush()

    ours = catalog.get_variant_by_sku(merchant_id, "CASE-IP16-BLK")
    theirs = catalog.get_variant_by_sku(OTHER_MERCHANT_ID, "CASE-IP16-BLK")

    assert ours is not None and theirs is not None
    assert ours.id != theirs.id
    assert ours.price == Decimal("999.00")
    assert theirs.price == Decimal("1.00")
    assert ours.product_slug == "aerocase_pro"
    assert theirs.product_slug == "impostor_case"


# --------------------------------------------------------------------------
# 3. Category filtering
# --------------------------------------------------------------------------


def test_search_filters_by_category(catalog: CatalogService, merchant_id: uuid.UUID) -> None:
    results = catalog.search(merchant_id, VariantQuery(category_slug="phone_case"))

    assert results
    assert {v.category_slug for v in results} == {"phone_case"}
    assert "BUDS-AIR-BLK" not in {v.sku for v in results}


def test_search_filters_by_budget(catalog: CatalogService, merchant_id: uuid.UUID) -> None:
    results = catalog.search(
        merchant_id, VariantQuery(category_slug="phone_case", max_price=Decimal("1500.00"))
    )

    skus = {v.sku for v in results}
    assert "CASE-IP16-BLK" in skus  # 999
    assert "CASE-IP16-LTR-BLK" not in skus  # 1799, over budget
    assert all(v.price <= Decimal("1500.00") for v in results)


def test_search_filters_by_attribute(catalog: CatalogService, merchant_id: uuid.UUID) -> None:
    """JSONB containment across variant then product attributes (D§27)."""
    leather = catalog.search(merchant_id, VariantQuery(attributes={"material": "leather"}))
    slugs = {v.product_slug for v in leather}
    # Membership rather than equality: the filter's job is to return everything
    # made of leather, and asserting the exact set makes adding a leather
    # product a test failure instead of a catalogue change.
    assert "leatherline_folio" in slugs
    assert slugs, "the attribute filter matched nothing at all"

    black = catalog.search(
        merchant_id, VariantQuery(category_slug="phone_case", attributes={"color": "black"})
    )
    assert "CASE-IP16-BLK" in {v.sku for v in black}
    assert "CASE-IP16-BLU" not in {v.sku for v in black}


def test_search_filters_by_text(catalog: CatalogService, merchant_id: uuid.UUID) -> None:
    results = catalog.search(merchant_id, VariantQuery(search_text="LeatherLine"))
    assert {v.product_slug for v in results} == {"leatherline_folio"}


def test_text_search_is_case_insensitive(catalog: CatalogService, merchant_id: uuid.UUID) -> None:
    lower = {v.sku for v in catalog.search(merchant_id, VariantQuery(search_text="aerocase"))}
    upper = {v.sku for v in catalog.search(merchant_id, VariantQuery(search_text="AEROCASE"))}

    assert lower == upper
    assert "CASE-IP16-BLK" in lower


def test_text_search_matches_substrings_deliberately(
    catalog: CatalogService, merchant_id: uuid.UUID
) -> None:
    """Substring, not word, matching.

    "folio" matches both LeatherLine Folio and the FeltFolio sleeves. That is
    intended for a ~30-SKU catalog: it is deterministic and explainable, and M3
    scores text relevance separately (ADR-004) rather than relying on this
    filter to rank. Pinned here so the semantics are a decision rather than an
    accident.
    """
    slugs = {v.product_slug for v in catalog.search(merchant_id, VariantQuery(search_text="folio"))}

    assert "leatherline_folio" in slugs
    assert "feltfolio_sleeve_13" in slugs


def test_search_returns_one_row_per_variant(
    catalog: CatalogService, merchant_id: uuid.UUID, catalog_seed
) -> None:
    """ADR-009 / open question B7: the variant is the sellable unit."""
    results = catalog.search(merchant_id, VariantQuery())

    assert len(results) == catalog_seed.variant_count
    assert len({v.id for v in results}) == len(results)


def test_search_with_no_matches_returns_empty_not_an_approximation(
    catalog: CatalogService, merchant_id: uuid.UUID
) -> None:
    """R§14: never fabricate, never silently widen the constraint."""
    assert (
        catalog.search(
            merchant_id, VariantQuery(category_slug="phone_case", max_price=Decimal("1.00"))
        )
        == []
    )


def test_list_categories_is_the_vocabulary_the_search_tool_is_limited_to(
    catalog: CatalogService, merchant_id: uuid.UUID
) -> None:
    """ADR-009 / open question B2."""
    slugs = catalog.category_slugs(merchant_id)

    assert "phone_case" in slugs
    assert slugs == tuple(sorted(slugs)), "must be deterministic"
    assert catalog.category_exists(merchant_id, "phone_case")
    assert not catalog.category_exists(merchant_id, "hoverboards")


def test_the_attribute_vocabulary_is_read_from_the_merchants_own_rows(
    catalog: CatalogService, merchant_id: uuid.UUID
) -> None:
    """The same argument as the category enum, one level down.

    The model is told which attribute names each category uses so a stated
    requirement can be a filter rather than a guess. A guess is worse than a
    refusal here: a missing attribute always fails (`app.attributes`), so
    `noise_cancelling` where the catalogue records `anc` eliminates every
    product and returns nothing at all.
    """
    vocabulary = catalog.attribute_vocabulary(merchant_id)

    # Product-level and variant-level names are unioned, because that is the
    # view the ranking engine eliminates on.
    assert "anc" in vocabulary["earbuds"], "a product attribute"
    assert "color" in vocabulary["earbuds"], "a variant attribute"
    assert "wattage" in vocabulary["charger"]
    assert "material" in vocabulary["phone_case"]

    # Scoped to the category, not pooled: a charger's `wattage` must not become
    # a name the model offers for a t-shirt.
    assert "wattage" not in vocabulary.get("t_shirt", ())
    assert "anc" not in vocabulary.get("phone_case", ())

    # Byte-stable between runs, but no longer alphabetical: the list is
    # truncated to fit a hard request-size ceiling, so it is ordered by what a
    # buyer is most likely to filter on - variant-level names first (D§27's
    # "what differentiates a sellable version"), then by how many products carry
    # the name. Under plain alphabetical order `storage_gb` fell off the end of
    # the phone list and "a phone with 256GB" had no name to state.
    assert vocabulary == catalog.attribute_vocabulary(merchant_id), "must be stable between calls"
    phone = vocabulary["smartphone"]
    assert phone.index("storage_gb") < phone.index("battery_mah")
    assert phone.index("ram_gb") < phone.index("operating_system")


# --------------------------------------------------------------------------
# 4. SKU retrieval  /  5. Authoritative price
# --------------------------------------------------------------------------


def test_sku_lookup_returns_the_authoritative_row(
    catalog: CatalogService, merchant_id: uuid.UUID
) -> None:
    variant = catalog.get_variant_by_sku(merchant_id, "CASE-IP16-BLK")

    assert variant is not None
    assert variant.sku == "CASE-IP16-BLK"
    assert variant.price == Decimal("999.00")
    assert variant.currency == "INR"
    assert variant.product_name == "AeroCase Pro"


def test_a_fabricated_sku_is_rejected(catalog: CatalogService, merchant_id: uuid.UUID) -> None:
    """architecture.md A§30, pre-submission gate PG-2.

    Nothing is fuzzy-matched or corrected: an approximate match would be a guess
    about what the buyer is purchasing.
    """
    for fabricated in ("FAKE-SKU-123", "case-ip16-blk", "CASE-IP16-BLK ", "CASE-IP16-BLKX"):
        assert catalog.get_variant_by_sku(merchant_id, fabricated) is None


def test_authoritative_price_comes_back_as_decimal_with_its_currency(
    catalog: CatalogService, merchant_id: uuid.UUID, variant_id
) -> None:
    """RULE 6, ADR-008."""
    result = catalog.get_authoritative_price(merchant_id, variant_id("CASE-IP16-BLK"))

    assert result is not None
    price, currency = result
    assert isinstance(price, Decimal)
    assert not isinstance(price, float)
    assert price == Decimal("999.00")
    assert currency == "INR"


def test_authoritative_price_reflects_a_catalog_change_immediately(
    session: Session, catalog: CatalogService, merchant_id: uuid.UUID, variant_id
) -> None:
    """RULE 12, and the mechanism ADR-014's price-drift detection rests on.

    The Policy Engine re-reads through this method rather than trusting a value
    it was handed, so a change made after a quote must be visible at once.
    """
    vid = variant_id("CASE-IP16-BLK")
    assert catalog.get_authoritative_price(merchant_id, vid) == (Decimal("999.00"), "INR")

    session.get(ProductVariant, vid).price = Decimal("1799.00")
    session.flush()

    assert catalog.get_authoritative_price(merchant_id, vid) == (Decimal("1799.00"), "INR")


def test_authoritative_price_of_an_unknown_variant_is_none(
    catalog: CatalogService, merchant_id: uuid.UUID
) -> None:
    assert catalog.get_authoritative_price(merchant_id, uuid.uuid4()) is None


# --------------------------------------------------------------------------
# Active flags
# --------------------------------------------------------------------------


def test_an_inactive_product_hides_its_variants(
    session: Session, catalog: CatalogService, merchant_id: uuid.UUID, product_id, variant_id
) -> None:
    """An active variant of a deactivated product is not sellable."""
    session.get(Product, product_id("aerocase_pro")).is_active = False
    session.flush()

    assert catalog.get_variant_by_sku(merchant_id, "CASE-IP16-BLK") is None
    assert catalog.get_variant(merchant_id, variant_id("CASE-IP16-BLK")) is None
    assert "CASE-IP16-BLK" not in {
        v.sku for v in catalog.search(merchant_id, VariantQuery(category_slug="phone_case"))
    }


def test_an_inactive_variant_is_excluded_but_its_siblings_are_not(
    session: Session, catalog: CatalogService, merchant_id: uuid.UUID, variant_id
) -> None:
    session.get(ProductVariant, variant_id("CASE-IP16-BLU")).is_active = False
    session.flush()

    skus = {v.sku for v in catalog.search(merchant_id, VariantQuery(category_slug="phone_case"))}
    assert "CASE-IP16-BLU" not in skus
    assert "CASE-IP16-BLK" in skus


# --------------------------------------------------------------------------
# Determinism
# --------------------------------------------------------------------------


def test_search_is_deterministic_across_repeated_calls(
    catalog: CatalogService, merchant_id: uuid.UUID
) -> None:
    """R§8: the same request against the same catalog gives the same answer."""
    query = VariantQuery(category_slug="phone_case")
    runs = [[v.sku for v in catalog.search(merchant_id, query)] for _ in range(4)]

    assert all(run == runs[0] for run in runs)


def test_search_is_ordered_by_price_then_sku(
    catalog: CatalogService, merchant_id: uuid.UUID
) -> None:
    results = catalog.search(merchant_id, VariantQuery(category_slug="phone_case"))
    keys = [(v.price, v.sku) for v in results]

    assert keys == sorted(keys)


# --------------------------------------------------------------------------
# Relationships
# --------------------------------------------------------------------------


def test_related_products_are_candidates_ordered_by_priority(
    catalog: CatalogService, merchant_id: uuid.UUID, product_id
) -> None:
    """D§17. Candidates only — the caller still checks compatibility and stock."""
    related = catalog.get_related_products(
        merchant_id, product_id("aerocase_pro"), relationship_types=["cross_sell"]
    )

    assert [r.product.slug for r in related] == ["guardglass_2_5d", "voltedge_30w"]
    assert [r.priority for r in related] == [1, 2]
    assert {r.relationship_type for r in related} == {"cross_sell"}


def test_related_products_are_merchant_scoped(catalog: CatalogService, product_id) -> None:
    assert catalog.get_related_products(OTHER_MERCHANT_ID, product_id("aerocase_pro")) == []


def test_merged_attributes_let_the_variant_override_its_product(
    catalog: CatalogService, merchant_id: uuid.UUID
) -> None:
    """D§27: variant attributes differentiate the sellable versions."""
    variant = catalog.get_variant_by_sku(merchant_id, "CASE-IP16-BLK")

    assert variant is not None
    assert variant.product_attributes["material"] == "TPU"
    assert variant.attributes["color"] == "black"
    assert variant.merged_attributes == {**variant.product_attributes, "color": "black"}


# --------------------------------------------------------------------------
# Batch and optional-filter surface
# --------------------------------------------------------------------------


def test_get_variants_hydrates_a_set_of_ids(
    catalog: CatalogService, merchant_id: uuid.UUID, variant_id
) -> None:
    ids = [variant_id("CASE-IP16-BLK"), variant_id("BUDS-LITE")]

    views = catalog.get_variants(merchant_id, ids)

    assert {v.sku for v in views} == {"CASE-IP16-BLK", "BUDS-LITE"}
    assert [v.sku for v in views] == sorted(v.sku for v in views), "deterministic order"


def test_batch_lookups_of_nothing_query_nothing(
    catalog: CatalogService, merchant_id: uuid.UUID
) -> None:
    assert catalog.get_variants(merchant_id, []) == []
    assert catalog.get_products(merchant_id, []) == []


def test_batch_lookups_silently_drop_ids_from_another_merchant(
    catalog: CatalogService, merchant_id: uuid.UUID, variant_id
) -> None:
    """A batch is still scoped; unknown or foreign ids are simply absent."""
    views = catalog.get_variants(merchant_id, [variant_id("CASE-IP16-BLK"), uuid.uuid4()])

    assert [v.sku for v in views] == ["CASE-IP16-BLK"]
    assert catalog.get_variants(OTHER_MERCHANT_ID, [variant_id("CASE-IP16-BLK")]) == []


def test_search_can_filter_by_currency(catalog: CatalogService, merchant_id: uuid.UUID) -> None:
    """ADR-008: currency is explicit and never assumed."""
    assert catalog.search(merchant_id, VariantQuery(currency="INR"))
    assert catalog.search(merchant_id, VariantQuery(currency="USD")) == []


def test_search_can_be_limited(catalog: CatalogService, merchant_id: uuid.UUID) -> None:
    limited = catalog.search(merchant_id, VariantQuery(category_slug="phone_case", limit=2))
    full = catalog.search(merchant_id, VariantQuery(category_slug="phone_case"))

    assert len(limited) == 2
    assert [v.sku for v in limited] == [v.sku for v in full[:2]], "limit keeps the ordering"
