"""CompatibilityService — resolution and validation (ADR-003).

The two properties that matter most:

* an unresolvable device produces a **question**, never a guess;
* an incompatible product is **removed**, never merely ranked lower.

The second is the one D§15 spells out as unsafe to get wrong: an incompatible
product that is cheaper must not be able to win.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from sqlalchemy.orm import Session

from app.db.models import CompatibilityTarget, Product
from app.domain import ResolutionFailure, ResolvedTarget, UnresolvedTarget
from app.services import CatalogService, CompatibilityService
from app.services.catalog_service import VariantQuery
from app.services.compatibility_service import RULE_TYPE_EXPANSION, constraints_satisfied
from tests.services.conftest import OTHER_MERCHANT_ID

pytestmark = pytest.mark.requires_db


# --------------------------------------------------------------------------
# 6. Canonical target resolution   7. Alias resolution
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "phrase",
    [
        "iPhone 16",
        "iphone 16",
        "IPHONE 16",
        "  iPhone   16  ",
        "iPhone-16",
        "iphone_16",
    ],
)
def test_normalization_resolves_punctuation_and_case(
    compatibility: CompatibilityService, phrase: str
) -> None:
    resolved = compatibility.resolve_target(phrase)

    assert isinstance(resolved, ResolvedTarget)
    assert resolved.canonical_identifier == "iphone_16"
    assert resolved.target_type == "phone_model"
    assert resolved.display_name == "iPhone 16"
    assert resolved.requested_text == phrase


@pytest.mark.parametrize("alias", ["iphone16", "apple_iphone_16", "Apple iPhone 16", "iPhone16"])
def test_aliases_resolve_what_normalization_alone_cannot(
    compatibility: CompatibilityService, alias: str
) -> None:
    """The reason `compatibility_targets.aliases` exists.

    `normalize_token("iphone16")` is `"iphone16"`, which is not `"iphone_16"`.
    Only the alias column bridges that.
    """
    resolved = compatibility.resolve_target(alias)

    assert isinstance(resolved, ResolvedTarget)
    assert resolved.canonical_identifier == "iphone_16"


def test_laptop_and_port_targets_resolve_too(compatibility: CompatibilityService) -> None:
    laptop = compatibility.resolve_target("MacBook Air M3")
    port = compatibility.resolve_target("USB-C")

    assert isinstance(laptop, ResolvedTarget)
    assert (laptop.canonical_identifier, laptop.target_type) == (
        "macbook_air_m3",
        "laptop_model",
    )
    assert isinstance(port, ResolvedTarget)
    assert (port.canonical_identifier, port.target_type) == ("usb_c", "device_port")


def test_resolution_can_be_narrowed_to_one_kind(compatibility: CompatibilityService) -> None:
    assert isinstance(
        compatibility.resolve_target("iPhone 16", target_type="phone_model"), ResolvedTarget
    )

    narrowed = compatibility.resolve_target("iPhone 16", target_type="laptop_model")
    assert isinstance(narrowed, UnresolvedTarget)
    assert narrowed.reason is ResolutionFailure.UNKNOWN_TARGET


def test_an_unsupported_target_kind_fails_loudly(
    compatibility: CompatibilityService,
) -> None:
    """Silently returning nothing would read as "no such device"."""
    with pytest.raises(ValueError, match="target_type"):
        compatibility.resolve_target("iPhone 16", target_type="spaceship")


# --------------------------------------------------------------------------
# 8. Unknown target handling — never guess
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "phrase",
    ["Xperia 5", "Nokia 3310", "my new phone", "the blue one", "iphone 17"],
)
def test_an_unknown_device_is_unresolved_rather_than_approximated(
    compatibility: CompatibilityService, phrase: str
) -> None:
    """R§5, L§18, ADR-003: no substring match, no nearest match, no guess."""
    result = compatibility.resolve_target(phrase)

    assert isinstance(result, UnresolvedTarget)
    assert result.resolved is False
    assert result.reason is ResolutionFailure.UNKNOWN_TARGET
    assert result.requested_text == phrase


def test_a_near_miss_does_not_resolve_to_its_neighbour(
    compatibility: CompatibilityService,
) -> None:
    """`iphone_15` is a valid token and a completely wrong answer."""
    result = compatibility.resolve_target("iPhone 16 Pro Max")

    assert isinstance(result, UnresolvedTarget)


@pytest.mark.parametrize("phrase", ["", "   ", "???", "!!!"])
def test_text_that_normalizes_to_nothing_is_reported_as_empty(
    compatibility: CompatibilityService, phrase: str
) -> None:
    result = compatibility.resolve_target(phrase)

    assert isinstance(result, UnresolvedTarget)
    assert result.reason is ResolutionFailure.EMPTY


def test_ambiguity_returns_the_candidates_rather_than_picking_one(
    session: Session, compatibility: CompatibilityService
) -> None:
    """ADR-003 requires a clarification, not a coin flip.

    The seed guarantees no token resolves twice, so ambiguity is constructed
    here: a second target kind claiming the same alias.
    """
    session.add(
        CompatibilityTarget(
            target_type="laptop_model",
            canonical_identifier="iphone_16",  # same identifier, different kind
            display_name="iPhone 16 Laptop Dock",
            aliases=[],
        )
    )
    session.flush()

    result = compatibility.resolve_target("iPhone 16")

    assert isinstance(result, UnresolvedTarget)
    assert result.reason is ResolutionFailure.AMBIGUOUS_TARGET
    assert {c.target_type for c in result.candidates} == {"phone_model", "laptop_model"}


def test_an_inactive_target_stops_resolving(
    session: Session, compatibility: CompatibilityService
) -> None:
    target = session.execute(
        CompatibilityTarget.__table__.select().where(
            CompatibilityTarget.canonical_identifier == "pixel_9"
        )
    ).one()
    session.get(CompatibilityTarget, target.id).is_active = False
    session.flush()

    assert isinstance(compatibility.resolve_target("Pixel 9"), UnresolvedTarget)


def test_the_known_vocabulary_can_be_listed_for_clarification(
    compatibility: CompatibilityService,
) -> None:
    phones = compatibility.list_targets(target_type="phone_model")
    identifiers = {t.canonical_identifier for t in phones}

    # A superset, not an equality: the vocabulary grows with the catalogue, and
    # a literal list here would fail the application for stocking more phones.
    # The three that must always be present are the ones the specification's
    # worked examples and the no-match path depend on.
    assert {"iphone_16", "iphone_15", "pixel_9"} <= identifiers
    assert all(t.display_name for t in phones)


# --------------------------------------------------------------------------
# 9. Compatible products   10. Incompatible exclusion
# --------------------------------------------------------------------------


def resolve(service: CompatibilityService, phrase: str) -> ResolvedTarget:
    target = service.resolve_target(phrase)
    assert isinstance(target, ResolvedTarget)
    return target


def test_compatible_products_are_returned(
    compatibility: CompatibilityService, merchant_id: uuid.UUID, catalog: CatalogService
) -> None:
    target = resolve(compatibility, "iPhone 16")
    ids = compatibility.compatible_product_ids(merchant_id, target)
    slugs = {p.slug for p in catalog.get_products(merchant_id, list(ids))}

    assert {"aerocase_pro", "shieldcase_premium", "leatherline_folio"} <= slugs


def test_an_incompatible_product_is_excluded_even_though_it_is_cheaper(
    compatibility: CompatibilityService,
    catalog: CatalogService,
    merchant_id: uuid.UUID,
) -> None:
    """D§15 and R§17 RULE 4, stated as the failure they forbid.

    The iPhone 15 case is ₹899 — cheaper than every compatible iPhone 16 case.
    If compatibility were a score rather than a filter, it could win.
    """
    target = resolve(compatibility, "iPhone 16")
    cases = catalog.search(merchant_id, VariantQuery(category_slug="phone_case"))

    cheapest_overall = min(cases, key=lambda v: v.price)
    assert cheapest_overall.sku == "CASE-IP15-BLK"

    compatible = compatibility.filter_variants(merchant_id, cases, target)

    assert "CASE-IP15-BLK" not in {v.sku for v in compatible}
    assert "CASE-IP16-BLK" in {v.sku for v in compatible}


def test_filtering_preserves_the_input_order(
    compatibility: CompatibilityService, catalog: CatalogService, merchant_id: uuid.UUID
) -> None:
    """R§8: a deterministic ordering must survive the filter."""
    target = resolve(compatibility, "iPhone 16")
    cases = catalog.search(merchant_id, VariantQuery(category_slug="phone_case"))

    filtered = compatibility.filter_variants(merchant_id, cases, target)

    assert [v.sku for v in filtered] == [v.sku for v in cases if v in filtered]


def test_every_variant_of_a_compatible_product_survives(
    compatibility: CompatibilityService, catalog: CatalogService, merchant_id: uuid.UUID
) -> None:
    """Compatibility attaches to the product; price and stock to the variant."""
    target = resolve(compatibility, "iPhone 16")
    cases = catalog.search(merchant_id, VariantQuery(category_slug="phone_case"))

    filtered = compatibility.filter_variants(merchant_id, cases, target)
    aerocase = {v.sku for v in filtered if v.product_slug == "aerocase_pro"}

    assert aerocase == {"CASE-IP16-BLK", "CASE-IP16-BLU", "CASE-IP16-CLR"}


def test_a_resolvable_device_with_no_compatible_products_returns_empty(
    compatibility: CompatibilityService, merchant_id: uuid.UUID
) -> None:
    """R§14: a real no-match, distinct from a device we failed to understand."""
    target = resolve(compatibility, "Pixel 9")

    assert target.canonical_identifier == "pixel_9"
    assert compatibility.compatible_product_ids(merchant_id, target) == set()


def test_rule_type_expansion_lets_a_phone_match_both_cases_and_chargers(
    compatibility: CompatibilityService, catalog: CatalogService, merchant_id: uuid.UUID
) -> None:
    """ADR-003: `phone_model` rules and the broader `device` rules both match."""
    assert RULE_TYPE_EXPANSION["phone_model"] == ("phone_model", "device")

    target = resolve(compatibility, "iPhone 16")
    slugs = {
        p.slug
        for p in catalog.get_products(
            merchant_id, list(compatibility.compatible_product_ids(merchant_id, target))
        )
    }

    assert "aerocase_pro" in slugs  # phone_model rule
    assert "voltedge_30w" in slugs  # device rule


def test_compatibility_is_merchant_scoped(
    compatibility: CompatibilityService,
) -> None:
    target = resolve(compatibility, "iPhone 16")

    assert compatibility.compatible_product_ids(OTHER_MERCHANT_ID, target) == set()


def test_an_inactive_product_is_not_compatible(
    session: Session, compatibility: CompatibilityService, merchant_id: uuid.UUID, product_id
) -> None:
    target = resolve(compatibility, "iPhone 16")
    assert compatibility.is_compatible(merchant_id, product_id("aerocase_pro"), target)

    session.get(Product, product_id("aerocase_pro")).is_active = False
    session.flush()

    assert not compatibility.is_compatible(merchant_id, product_id("aerocase_pro"), target)


def test_results_are_deterministic(
    compatibility: CompatibilityService, merchant_id: uuid.UUID
) -> None:
    target = resolve(compatibility, "iPhone 16")
    runs = [compatibility.compatible_product_ids(merchant_id, target) for _ in range(4)]

    assert all(run == runs[0] for run in runs)


def test_filtering_an_empty_candidate_set_queries_nothing(
    compatibility: CompatibilityService, merchant_id: uuid.UUID
) -> None:
    target = resolve(compatibility, "iPhone 16")

    assert compatibility.filter_variants(merchant_id, [], target) == []


# --------------------------------------------------------------------------
# Constraint predicates (ADR-003, open question B3) — pure, no database
# --------------------------------------------------------------------------


class TestConstraintPredicates:
    """`constraints` are predicates on the product's own attributes."""

    def test_no_constraints_is_satisfied(self) -> None:
        assert constraints_satisfied({"wattage": 30}, {})

    def test_minimum_is_inclusive(self) -> None:
        assert constraints_satisfied({"wattage": 20}, {"minimum_wattage": 20})
        assert constraints_satisfied({"wattage": 30}, {"minimum_wattage": 20})
        assert not constraints_satisfied({"wattage": 18}, {"minimum_wattage": 20})

    def test_maximum_is_inclusive(self) -> None:
        assert constraints_satisfied({"length_m": 2}, {"maximum_length_m": 2})
        assert not constraints_satisfied({"length_m": 3}, {"maximum_length_m": 2})

    def test_equality_for_everything_else(self) -> None:
        assert constraints_satisfied({"fast_charge": True}, {"fast_charge": True})
        assert not constraints_satisfied({"fast_charge": False}, {"fast_charge": True})
        assert constraints_satisfied({"port_type": "usb_c"}, {"port_type": "usb_c"})

    def test_string_equality_ignores_case(self) -> None:
        assert constraints_satisfied({"port_type": "USB_C"}, {"port_type": "usb_c"})

    def test_a_missing_attribute_fails(self) -> None:
        """A requirement the catalog cannot evidence has not been shown to hold."""
        assert not constraints_satisfied({}, {"minimum_wattage": 20})
        assert not constraints_satisfied({"wattage": 30}, {"fast_charge": True})

    def test_booleans_are_not_numbers(self) -> None:
        """`True >= 20` must not be treated as a comparison."""
        assert not constraints_satisfied({"wattage": True}, {"minimum_wattage": 1})

    def test_one_is_not_true(self) -> None:
        """`1 == True` is true in Python and is not what a catalog means."""
        assert not constraints_satisfied({"fast_charge": 1}, {"fast_charge": True})

    def test_numeric_strings_compare_numerically(self) -> None:
        assert constraints_satisfied({"wattage": "30"}, {"minimum_wattage": 20})

    def test_a_non_numeric_value_fails_a_numeric_predicate(self) -> None:
        assert not constraints_satisfied({"wattage": "fast"}, {"minimum_wattage": 20})

    def test_all_predicates_must_hold(self) -> None:
        attributes = {"wattage": 30, "fast_charge": True}
        assert constraints_satisfied(attributes, {"minimum_wattage": 20, "fast_charge": True})
        assert not constraints_satisfied(attributes, {"minimum_wattage": 65, "fast_charge": True})


def test_a_charger_that_fails_its_own_predicate_is_not_compatible(
    session: Session,
    compatibility: CompatibilityService,
    merchant_id: uuid.UUID,
    product_id,
) -> None:
    """The predicate is enforced, not decorative.

    VoltEdge 30W is compatible with an iPhone 16 *provided* it supplies at least
    20W (D§14). Drop its wattage below that and the rule stops holding, even
    though the row still exists.
    """
    target = resolve(compatibility, "iPhone 16")
    charger = product_id("voltedge_30w")
    assert compatibility.is_compatible(merchant_id, charger, target)

    product = session.get(Product, charger)
    product.attributes = {**product.attributes, "wattage": 5}
    session.flush()

    assert not compatibility.is_compatible(merchant_id, charger, target)


def test_seeded_catalog_prices_are_untouched_by_compatibility_filtering(
    compatibility: CompatibilityService, catalog: CatalogService, merchant_id: uuid.UUID
) -> None:
    """Filtering must not transform the rows it passes through."""
    target = resolve(compatibility, "iPhone 16")
    cases = catalog.search(merchant_id, VariantQuery(category_slug="phone_case"))
    filtered = compatibility.filter_variants(merchant_id, cases, target)

    by_sku = {v.sku: v for v in filtered}
    assert by_sku["CASE-IP16-BLK"].price == Decimal("999.00")
    assert by_sku["CASE-IP16-SHD-BLK"].price == Decimal("1299.00")
