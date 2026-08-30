"""Validation for the seed catalog.

Every rule here is checkable **without a database**, which matters for two
reasons. A malformed catalog fails with a message naming the offending row
rather than as an opaque constraint violation halfway through a transaction.
And on a machine with no PostgreSQL, catalog integrity is still verified.

The rules fall into three groups:

*Shape* — slugs and compatibility identifiers are canonical tokens, SKUs are
uppercase tokens, quantities are not negative, prices are non-negative decimals.

*Money* — a price must arrive as a **string**. ``json.loads`` turns ``999.00``
into a float before any validator can intervene, and no float is ever allowed
near a price (ADR-008). A numeric literal in the JSON is rejected outright.

*Referential closure* — every category parent, every product category, every
relationship endpoint and every compatibility identifier resolves inside the
file; slugs and SKUs are unique. The compatibility check in particular cannot be
a foreign key, because ``compatibility_rules.target_type`` and
``compatibility_targets.target_type`` are different axes (ADR-003), so it is
enforced here and by the service layer instead.
"""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.canonical import is_canonical_token, normalize_token

CATALOG_PATH = Path(__file__).parent / "data" / "catalog.json"

CanonicalToken = Annotated[str, Field(min_length=1, max_length=128)]


def _check_canonical(value: str, what: str) -> str:
    if not is_canonical_token(value):
        raise ValueError(
            f"{what} {value!r} is not a canonical token "
            f"(lowercase alphanumeric segments joined by - or _)"
        )
    return value


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class VariantSeed(_Strict):
    sku: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=255)
    price: Decimal
    quantity: int = Field(ge=0)
    attributes: dict[str, Any] = Field(default_factory=dict)

    @field_validator("sku")
    @classmethod
    def _sku_shape(cls, value: str) -> str:
        if not value or value != value.upper():
            raise ValueError(f"SKU {value!r} must be uppercase")
        if not all(ch.isalnum() or ch in "-_" for ch in value) or not value[0].isalnum():
            raise ValueError(f"SKU {value!r} must match ^[A-Z0-9][A-Z0-9_-]*$")
        return value

    @field_validator("price", mode="before")
    @classmethod
    def _price_must_be_a_string(cls, value: object) -> Decimal:
        """ADR-008: money is a string in JSON so it never becomes a float."""
        if not isinstance(value, str):
            raise ValueError(
                f'price must be a JSON string such as "999.00", not {type(value).__name__}; '
                "a JSON number would be parsed as a float before validation"
            )
        return Decimal(value)

    @field_validator("price")
    @classmethod
    def _price_scale(cls, value: Decimal) -> Decimal:
        if value < 0:
            raise ValueError("price must not be negative")
        if -value.as_tuple().exponent > 2:
            raise ValueError(f"price {value} has more than two decimal places")
        return value


class CompatibilitySeed(_Strict):
    target_type: Literal["phone_model", "laptop_model", "device", "device_port"]
    target_identifier: CanonicalToken
    constraints: dict[str, Any] = Field(default_factory=dict)

    @field_validator("target_identifier")
    @classmethod
    def _identifier_shape(cls, value: str) -> str:
        return _check_canonical(value, "compatibility target_identifier")


class ProductSeed(_Strict):
    slug: CanonicalToken
    name: str = Field(min_length=1, max_length=255)
    category: CanonicalToken
    brand: str | None = Field(default=None, max_length=128)
    description: str | None = None
    attributes: dict[str, Any] = Field(default_factory=dict)
    tags: list[str] = Field(default_factory=list)
    variants: list[VariantSeed] = Field(min_length=1)
    compatibility: list[CompatibilitySeed] = Field(default_factory=list)

    @field_validator("slug", "category")
    @classmethod
    def _slug_shape(cls, value: str) -> str:
        return _check_canonical(value, "product slug or category")

    @model_validator(mode="after")
    def _variant_skus_are_unique(self) -> ProductSeed:
        skus = [variant.sku for variant in self.variants]
        if len(set(skus)) != len(skus):
            raise ValueError(f"product {self.slug!r} repeats a SKU")
        return self


class CategorySeed(_Strict):
    slug: CanonicalToken
    name: str = Field(min_length=1, max_length=255)
    parent: str | None = None

    @field_validator("slug")
    @classmethod
    def _slug_shape(cls, value: str) -> str:
        return _check_canonical(value, "category slug")


class CompatibilityTargetSeed(_Strict):
    target_type: Literal["phone_model", "laptop_model", "device_port"]
    canonical_identifier: CanonicalToken
    display_name: str = Field(min_length=1, max_length=160)
    aliases: list[str] = Field(default_factory=list)

    @field_validator("canonical_identifier")
    @classmethod
    def _identifier_shape(cls, value: str) -> str:
        return _check_canonical(value, "canonical_identifier")

    @field_validator("aliases")
    @classmethod
    def _aliases_are_already_normalized(cls, values: list[str]) -> list[str]:
        """An alias is compared against normalized user text.

        Storing an alias that ``normalize_token`` would never produce means the
        alias can never match, and the failure is silent — the buyer just gets a
        clarification question forever.
        """
        for alias in values:
            normalized = normalize_token(alias)
            if alias != normalized:
                raise ValueError(f"alias {alias!r} is not normalized; store {normalized!r} instead")
        return values


class RelationshipSeed(_Strict):
    source: CanonicalToken
    target: CanonicalToken
    type: Literal["cross_sell", "bundle", "related"]
    priority: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def _endpoints_differ(self) -> RelationshipSeed:
        if self.source == self.target:
            raise ValueError(f"relationship {self.source!r} points at itself")
        return self


class MerchantSeed(_Strict):
    name: str = Field(min_length=1, max_length=255)
    description: str | None = None
    currency: str = Field(min_length=3, max_length=3)

    @field_validator("currency")
    @classmethod
    def _currency_shape(cls, value: str) -> str:
        if not value.isalpha() or value != value.upper():
            raise ValueError(f"currency {value!r} must be an uppercase ISO-4217 code")
        return value


class CatalogSeed(BaseModel):
    """The whole seed file, validated."""

    model_config = ConfigDict(extra="ignore", frozen=True)

    merchant: MerchantSeed
    categories: list[CategorySeed] = Field(min_length=1)
    compatibility_targets: list[CompatibilityTargetSeed] = Field(default_factory=list)
    products: list[ProductSeed] = Field(min_length=1)
    relationships: list[RelationshipSeed] = Field(default_factory=list)

    # -- cross-record rules --------------------------------------------------

    @model_validator(mode="after")
    def _category_tree_is_sound(self) -> CatalogSeed:
        slugs = [category.slug for category in self.categories]
        if len(set(slugs)) != len(slugs):
            raise ValueError("duplicate category slug")

        by_slug = {category.slug: category for category in self.categories}
        for category in self.categories:
            if category.parent is not None and category.parent not in by_slug:
                raise ValueError(
                    f"category {category.slug!r} has unknown parent {category.parent!r}"
                )

        # Walk to the root from every node; a cycle would otherwise only show up
        # as an infinite loop somewhere much later.
        for category in self.categories:
            seen: set[str] = set()
            cursor: str | None = category.slug
            while cursor is not None:
                if cursor in seen:
                    raise ValueError(f"category cycle involving {category.slug!r}")
                seen.add(cursor)
                cursor = by_slug[cursor].parent
        return self

    @model_validator(mode="after")
    def _products_are_unique_and_resolvable(self) -> CatalogSeed:
        slugs = [product.slug for product in self.products]
        if len(set(slugs)) != len(slugs):
            raise ValueError("duplicate product slug")

        category_slugs = {category.slug for category in self.categories}
        for product in self.products:
            if product.category not in category_slugs:
                raise ValueError(
                    f"product {product.slug!r} references unknown category {product.category!r}"
                )

        all_skus = [variant.sku for product in self.products for variant in product.variants]
        if len(set(all_skus)) != len(all_skus):
            duplicates = sorted({sku for sku in all_skus if all_skus.count(sku) > 1})
            raise ValueError(f"SKU is not unique within the merchant: {duplicates}")
        return self

    @model_validator(mode="after")
    def _compatibility_identifiers_resolve(self) -> CatalogSeed:
        """Every rule identifier must exist in the target vocabulary.

        Not expressible as a foreign key: a rule's ``target_type`` says how the
        product relates to the target, while a target's ``target_type`` says
        what kind of thing the identifier names, and the two vocabularies
        deliberately differ (ADR-003). So the join is on the identifier alone.
        """
        known = {target.canonical_identifier for target in self.compatibility_targets}
        for product in self.products:
            for rule in product.compatibility:
                if rule.target_identifier not in known:
                    raise ValueError(
                        f"product {product.slug!r} is compatible with unknown target "
                        f"{rule.target_identifier!r}; add it to compatibility_targets"
                    )
        return self

    @model_validator(mode="after")
    def _compatibility_targets_are_unique(self) -> CatalogSeed:
        keys = [
            (target.target_type, target.canonical_identifier)
            for target in self.compatibility_targets
        ]
        if len(set(keys)) != len(keys):
            raise ValueError("duplicate (target_type, canonical_identifier)")

        # An alias that collides with another target's identifier or aliases
        # would make resolution ambiguous, which ADR-003 requires to be a
        # clarification rather than a coin flip. Better to catch it here.
        seen: dict[str, str] = {}
        for target in self.compatibility_targets:
            for token in (target.canonical_identifier, *target.aliases):
                owner = f"{target.target_type}:{target.canonical_identifier}"
                if token in seen and seen[token] != owner:
                    raise ValueError(f"token {token!r} resolves to both {seen[token]} and {owner}")
                seen[token] = owner
        return self

    @model_validator(mode="after")
    def _relationships_resolve(self) -> CatalogSeed:
        product_slugs = {product.slug for product in self.products}
        for rel in self.relationships:
            for endpoint in (rel.source, rel.target):
                if endpoint not in product_slugs:
                    raise ValueError(f"relationship references unknown product {endpoint!r}")

        keys = [(rel.source, rel.target, rel.type) for rel in self.relationships]
        if len(set(keys)) != len(keys):
            raise ValueError("duplicate (source, target, type) relationship")
        return self

    # -- convenience ---------------------------------------------------------

    @property
    def variant_count(self) -> int:
        return sum(len(product.variants) for product in self.products)

    @property
    def rule_count(self) -> int:
        return sum(len(product.compatibility) for product in self.products)


def load_catalog(path: Path | None = None) -> CatalogSeed:
    """Read and validate the seed catalog. Touches no database."""
    source = path or CATALOG_PATH
    # parse_float is a second line of defence behind the per-field check: if a
    # future field carries money and nobody remembers the string rule, a bare
    # JSON float still cannot become a Python float.
    raw = json.loads(source.read_text(encoding="utf-8"), parse_float=Decimal)
    return CatalogSeed.model_validate(raw)
