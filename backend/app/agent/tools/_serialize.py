"""Turning domain values into what a tool returns (A§33, ADR-009, ADR-010).

Every rule here is a rule about what must *not* cross the boundary.

**Money is a fixed-scale string.** `"999.00"`, never `999.0` (ADR-008). A JSON
number becomes a float in most parsers before any validation can intervene, and
these payloads are read both by the model and — after the response builder — by
a browser.

**Stock is coarse.** `IN_STOCK` / `LOW_STOCK` / `OUT_OF_STOCK` and a boolean, no
quantities (ADR-009, closing E5). Exact counts stay in `check_inventory`, which
the agent uses for validation, and in the Policy Engine. A buyer-facing payload
that carried "3 left" would be publishing a merchant's stock position.

**No internal field, ever.** No ORM row, no `merchant_id`, no `is_active`, no
timestamps. A§33: structured, small, relevant, validated. Every field below is
one the model or the frontend has an actual use for.

Serialization is deliberately explicit rather than reflective. `asdict()` on a
domain value would export whatever the dataclass happens to hold, so a field
added later would start leaving the building without anyone deciding it should.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from app.domain.catalog import ProductDetail, VariantView
from app.domain.inventory import StockStatus
from app.domain.ranking import CrossSellCandidate, RankedCandidate

__all__ = [
    "money",
    "serialize_cross_sell",
    "serialize_product",
    "serialize_ranked",
    "serialize_variant",
]

#: Two places, always. `Decimal("999")` and `Decimal("999.00")` are equal and
#: must not serialize differently, or a client comparing strings sees a change
#: where there was none.
_SCALE = Decimal("0.01")


def money(amount: Decimal) -> str:
    """A monetary amount as a fixed-scale string (ADR-008)."""
    return str(amount.quantize(_SCALE))


def serialize_variant(
    variant: VariantView,
    *,
    stock_status: StockStatus | None = None,
    available: bool | None = None,
) -> dict[str, Any]:
    """One sellable row: what it is, what it costs, whether it can be bought."""
    payload: dict[str, Any] = {
        "product_id": str(variant.product_id),
        "variant_id": str(variant.id),
        "sku": variant.sku,
        "name": variant.product_name,
        "variant_name": variant.name,
        "category": variant.category_slug,
        "price": money(variant.price),
        "currency": variant.currency,
        "attributes": dict(variant.attributes),
    }
    if variant.brand:
        payload["brand"] = variant.brand
    if stock_status is not None:
        payload["stock_status"] = stock_status.value
    if available is not None:
        payload["available"] = available
    return payload


def serialize_product(product: ProductDetail) -> dict[str, Any]:
    """A product with every sellable variant under it.

    The product carries identity and description; each variant carries the price
    and SKU, because the variant is the sellable unit (ADR-002) and a payload
    keyed by product would have no single price to state.
    """
    summary = product.product
    return {
        "product_id": str(summary.id),
        "name": summary.name,
        "slug": summary.slug,
        "category": summary.category_slug,
        "brand": summary.brand,
        "description": summary.description,
        "attributes": dict(summary.attributes),
        "tags": list(summary.tags),
        "variants": [
            {
                "variant_id": str(variant.id),
                "sku": variant.sku,
                "variant_name": variant.name,
                "price": money(variant.price),
                "currency": variant.currency,
                "attributes": dict(variant.attributes),
            }
            for variant in product.variants
        ],
    }


def serialize_ranked(candidate: RankedCandidate) -> dict[str, Any]:
    """A ranked candidate, with the arithmetic that placed it (ADR-010).

    `reason` is the ranking engine's own label (closing A7). The model may
    paraphrase it in prose; it may not author it, because a model-written reason
    would be a claim about a computation the model did not perform.

    `score` is present so the ordering is inspectable. A client may ignore it;
    the demo does not.
    """
    payload = serialize_variant(candidate.variant, stock_status=candidate.stock_status)
    payload["rank"] = candidate.rank
    payload["reason"] = candidate.explanation.text
    payload["reason_code"] = candidate.explanation.label.value
    payload["score"] = {
        "final": str(candidate.score.final_score),
        "profile": candidate.score.profile_name,
        "components": {
            component.name: str(component.score) for component in candidate.score.components
        },
    }
    return payload


def serialize_cross_sell(candidate: CrossSellCandidate) -> dict[str, Any]:
    """An accessory the merchant explicitly related to a product (R§15).

    Grounded in `product_relationships`, then filtered by compatibility and
    stock. R§15's closing rule is that the system must not recommend products
    merely because they increase revenue, and the relationship row is what makes
    the difference between a suggestion and an invention.
    """
    payload = serialize_variant(candidate.variant, stock_status=candidate.stock_status)
    payload["relationship"] = candidate.relationship_type
    return payload
