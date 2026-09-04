"""Read-only catalog browsing.

**Why this module exists.** The catalog services have been complete since M2, but
nothing routed to them, so the only way a product could reach the browser was as
`recommendations[]` on a chat turn. A storefront — categories, a listing, a
product page — was therefore impossible to build without inventing data, which
F§9 forbids outright. This closes that gap by exposing what PostgreSQL already
holds.

**What it deliberately does not do.** No writing, no pricing decisions, no
ranking, no compatibility judgement, and no model. These handlers call
`CatalogService` and `InventoryService` — both on the trusted, deterministic side
of the boundary — and copy what comes back. Relevance ordering stays with the
ranking engine, reached through the agent; a listing sorts by the plain
attributes a shopper expects (price, name), never by a score.

Browsing is anonymous and needs no session: nothing here is scoped to a buyer,
and nothing here can move money.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session as DbSession

from app.agent.errors import ApiErrorCode
from app.api.schemas.catalog import (
    CatalogItem,
    CategoryItem,
    ProductDetailResponse,
    ProductListResponse,
    ProductSummaryItem,
)
from app.config import Settings, get_settings
from app.db.session import get_db
from app.repositories.variant_repository import VariantQuery
from app.services.catalog_service import CatalogService
from app.services.inventory_service import InventoryService

router = APIRouter(tags=["catalog"])

#: The orderings a listing offers. Deliberately a closed set: an arbitrary
#: `order_by` string would be both an injection surface and a way to ask for an
#: ordering the ranking engine owns.
SortKey = Literal["relevance", "price_asc", "price_desc", "name"]

#: A listing page. Bounded so a client cannot ask for the whole table.
MAX_LIMIT = 60


@router.get(
    "/categories",
    response_model=list[CategoryItem],
    summary="Every category this merchant sells into",
)
def list_categories(
    db: DbSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> list[CategoryItem]:
    """The category vocabulary, straight from PostgreSQL."""
    categories = CatalogService(db).list_categories(settings.default_merchant_id)
    return [CategoryItem.of(c) for c in categories]


@router.get(
    "/products",
    response_model=ProductListResponse,
    summary="Browse the catalog: one row per sellable variant",
)
def list_products(
    category: str | None = Query(default=None, description="Category slug."),
    q: str | None = Query(default=None, max_length=200, description="Free text."),
    max_price: str | None = Query(default=None, description='Decimal string, e.g. "1500.00".'),
    sort: SortKey = Query(default="relevance"),
    limit: int = Query(default=24, ge=1, le=MAX_LIMIT),
    db: DbSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> ProductListResponse:
    """A page of variants, with live stock for each.

    `max_price` arrives as a string and is parsed with `Decimal`, never `float` —
    the same rule the rest of the money path follows (ADR-008). A malformed value
    is a 422 rather than a silently ignored filter, because a budget that quietly
    stops applying is worse than one that fails.
    """
    merchant_id = settings.default_merchant_id
    catalog = CatalogService(db)

    ceiling: Decimal | None = None
    if max_price is not None:
        try:
            ceiling = Decimal(max_price)
        except (InvalidOperation, ValueError):
            raise HTTPException(
                status_code=422,  # Starlette renamed its 422 constant; the number is stable.
                detail={
                    "code": ApiErrorCode.VALIDATION_ERROR.value,
                    "message": 'max_price must be a decimal string such as "1500.00"',
                },
            ) from None

    # `ApiErrorCode` is F§25's closed eleven and must not grow, so an unknown
    # category reports as PRODUCT_NOT_FOUND rather than gaining a twelfth code.
    if category is not None and not catalog.category_exists(merchant_id, category):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": ApiErrorCode.PRODUCT_NOT_FOUND.value,
                "message": f"no category {category!r} for this merchant",
            },
        )

    # The repository's own limit is left unset so `total` can report how many
    # rows actually matched; paging happens below. The catalog is 32 variants,
    # so this reads the matched set, not the table.
    matched = catalog.search(
        merchant_id,
        VariantQuery(category_slug=category, search_text=q, max_price=ceiling),
    )

    ordered = _sort(matched, sort)
    page = ordered[:limit]

    stock = InventoryService(db).get_stock_map(merchant_id, [v.id for v in page])
    return ProductListResponse(
        items=[CatalogItem.of(v, stock.get(v.id)) for v in page],
        total=len(matched),
        categories=[CategoryItem.of(c) for c in catalog.list_categories(merchant_id)],
    )


@router.get(
    "/products/{slug}",
    response_model=ProductDetailResponse,
    summary="One product and every sellable version of it",
)
def get_product(
    slug: str,
    db: DbSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> ProductDetailResponse:
    """Product detail, addressed by slug because that is what a URL should carry."""
    merchant_id = settings.default_merchant_id
    catalog = CatalogService(db)

    detail = catalog.get_product_by_slug(merchant_id, slug)
    if detail is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": ApiErrorCode.PRODUCT_NOT_FOUND.value,
                "message": f"no product {slug!r} for this merchant",
            },
        )

    stock = InventoryService(db).get_stock_map(merchant_id, [v.id for v in detail.variants])
    related = catalog.get_related_products(merchant_id, detail.product.id)

    return ProductDetailResponse(
        product=ProductSummaryItem.of(detail.product),
        variants=[CatalogItem.of(v, stock.get(v.id)) for v in detail.variants],
        # A *candidate*, not a recommendation: R§15 requires cross-sells to be
        # grounded in compatibility and availability, which this route does not
        # judge. The UI presents them as "related", never as "recommended".
        related=[ProductSummaryItem.of(r.product) for r in related],
    )


def _sort(variants: list, key: SortKey) -> list:
    """Deterministic ordering, with SKU as the final tiebreak.

    `relevance` here means the catalog's own deterministic order, **not** a
    ranking score — scores belong to the ranking engine and reach a buyer only
    through the agent. Naming it "relevance" in the API while sorting by a score
    would blur exactly the line ADR-005 draws.
    """
    if key == "price_asc":
        return sorted(variants, key=lambda v: (v.price, v.sku))
    if key == "price_desc":
        return sorted(variants, key=lambda v: (-v.price, v.sku))
    if key == "name":
        return sorted(variants, key=lambda v: (v.product_name.lower(), v.name.lower(), v.sku))
    return list(variants)
