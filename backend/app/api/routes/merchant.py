"""The merchant dashboard API — `/api/merchant/*`.

**Authenticated and merchant-scoped** (ADR-023, superseding ADR-022's
single-tenant stance). Every handler depends on `require_merchant_id`, which
resolves the merchant from the **bearer token's user row** (`users.merchant_id`).
The merchant is never read from a path parameter, a query string or a request
body, and the request schemas are `extra="forbid"`, so there is no field a client
could put one in.

That keeps ADR-022's structural guarantee and strengthens it: a caller cannot
name a merchant, *and* cannot reach any merchant without proving they administer
one. A row whose `merchant_id` does not match is reported as *not found*, never
acted on. Without a token these routes answer 401; with a customer's token, 403.

**Reuses the deterministic services.** Reads go through `CatalogService` /
`InventoryService` / `OrderService`; writes through `MerchantCatalogService`,
which validates every field and lets the schema's CHECK constraints be the
backstop. Nothing here imports `app.llm` or `app.agent`, and no handler mutates
an order's state — the dashboard observes the commerce state machine, it does
not drive it.

**No fabricated numbers.** `/overview` aggregates come straight from the source
tables (`MerchantAnalyticsService`); revenue counts only `PAYMENT_CONFIRMED`
orders, because that is the only money the merchant has actually received.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy.orm import Session as DbSession

from app.agent.errors import ApiErrorCode
from app.api.deps import CurrentMerchant, require_merchant_id
from app.api.schemas.merchant import (
    CategoryCreateRequest,
    MerchantCategoryItem,
    MerchantOrderItem,
    MerchantOrderLine,
    MerchantOrderPage,
    MerchantOverviewResponse,
    MerchantProductDetailResponse,
    MerchantProductListResponse,
    MerchantVariantItem,
    ProductCreateRequest,
    ProductUpdateRequest,
    StockUpdateRequest,
    VariantCreateRequest,
    VariantUpdateRequest,
)
from app.config import Settings, get_settings
from app.db.models import Merchant, Order
from app.db.session import get_db
from app.domain.activity import MerchantAction, MerchantEntityType
from app.services.activity_service import ActivityService
from app.services.catalog_service import CatalogService
from app.services.inventory_service import InventoryService
from app.services.merchant_service import (
    MerchantAnalyticsService,
    MerchantCatalogService,
    MerchantError,
)
from app.services.order_service import OrderService

router = APIRouter(prefix="/merchant", tags=["merchant"])

_CODE_STATUS = {
    # 422, spelled as the number because Starlette renamed its constant and the
    # number is stable — the same choice `catalog.py` makes.
    "VALIDATION_ERROR": 422,
    "PRODUCT_NOT_FOUND": status.HTTP_404_NOT_FOUND,
    "VARIANT_NOT_FOUND": status.HTTP_404_NOT_FOUND,
}


def _fail(error: MerchantError) -> HTTPException:
    return HTTPException(
        status_code=_CODE_STATUS.get(error.code, status.HTTP_400_BAD_REQUEST),
        # `details` is part of the closed error body the frontend's Zod schema
        # expects (F§25); an empty object rather than an omitted key.
        detail={"code": error.code, "message": error.message, "details": {}},
    )


def _not_found(message: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail={
            "code": ApiErrorCode.PRODUCT_NOT_FOUND.value,
            "message": message,
            "details": {},
        },
    )


def _detail(
    catalog: CatalogService,
    inventory: InventoryService,
    merchant_id: uuid.UUID,
    product_id: uuid.UUID,
    writer: MerchantCatalogService,
) -> MerchantProductDetailResponse:
    """One product with every variant (active or not) and live stock."""
    try:
        detail = writer.get_product(merchant_id, product_id)
    except MerchantError as error:
        raise _fail(error) from error
    stock = inventory.get_stock_map(merchant_id, [v.id for v in detail.variants])
    product = detail.product
    rows = []
    for v in detail.variants:
        s = stock.get(v.id)
        rows.append(
            MerchantVariantItem(
                variant_id=v.id,
                product_id=product.id,
                product_slug=product.slug,
                product_name=product.name,
                variant_name=v.name,
                sku=v.sku,
                category=product.category_slug,
                price=str(v.price),
                currency=v.currency,
                quantity=s.quantity if s else 0,
                reserved_quantity=s.reserved_quantity if s else 0,
                available_quantity=s.available_quantity if s else 0,
                stock_status=(s.status.value if s else "OUT_OF_STOCK"),
                product_active=v.product_is_active,
                variant_active=v.is_active,
                attributes=v.merged_attributes,
            )
        )
    return MerchantProductDetailResponse(
        product_id=product.id,
        slug=product.slug,
        name=product.name,
        category=product.category_slug,
        description=product.description,
        brand=product.brand,
        is_active=all(v.product_is_active for v in detail.variants) if detail.variants else True,
        attributes=dict(product.attributes),
        tags=list(product.tags),
        variants=rows,
    )


# -- identity ----------------------------------------------------------


class MerchantMeResponse(BaseModel):
    """Who the dashboard is signed in as, and which merchant it administers."""

    id: uuid.UUID
    email: str
    role: str
    display_name: str | None = None
    merchant_id: uuid.UUID
    merchant_name: str


@router.get("/me", response_model=MerchantMeResponse, summary="The signed-in merchant")
def merchant_me(
    merchant: CurrentMerchant,
    db: DbSession = Depends(get_db),
) -> MerchantMeResponse:
    """The dashboard's boot call — 401 tells the client to show the login page.

    The merchant name is read from the `merchants` row rather than from
    configuration, so it is the tenant's own name once there is more than one.
    """
    assert merchant.merchant_id is not None  # require_merchant guarantees this
    row = db.get(Merchant, merchant.merchant_id)
    return MerchantMeResponse(
        id=merchant.id,
        email=merchant.email,
        role=merchant.role.value,
        display_name=merchant.display_name,
        merchant_id=merchant.merchant_id,
        merchant_name=row.name if row is not None else "",
    )


# -- overview ----------------------------------------------------------


@router.get("/overview", response_model=MerchantOverviewResponse, summary="Dashboard metrics")
def overview(
    db: DbSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
    merchant_id: uuid.UUID = Depends(require_merchant_id),
) -> MerchantOverviewResponse:
    result = MerchantAnalyticsService(db).overview(
        merchant_id, currency=settings.spending_limit_currency
    )
    return MerchantOverviewResponse.of(result)


# -- categories ------------------------------------------------------


@router.get("/categories", response_model=list[MerchantCategoryItem], summary="Merchant categories")
def list_categories(
    db: DbSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
    merchant_id: uuid.UUID = Depends(require_merchant_id),
) -> list[MerchantCategoryItem]:
    cats = CatalogService(db).list_categories(merchant_id)
    return [
        MerchantCategoryItem(id=c.id, slug=c.slug, name=c.name, parent_slug=c.parent_slug)
        for c in cats
    ]


@router.post(
    "/categories",
    response_model=MerchantCategoryItem,
    status_code=status.HTTP_201_CREATED,
    summary="Create a category",
)
def create_category(
    merchant: CurrentMerchant,
    body: CategoryCreateRequest,
    db: DbSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
    merchant_id: uuid.UUID = Depends(require_merchant_id),
) -> MerchantCategoryItem:
    try:
        category = MerchantCatalogService(db).create_category(
            merchant_id, name=body.name, slug=body.slug, parent_slug=body.parent
        )
    except MerchantError as error:
        raise _fail(error) from error
    ActivityService(db).record(
        merchant,
        MerchantAction.CATEGORY_CREATED,
        MerchantEntityType.CATEGORY,
        entity_id=category.id,
        subject=category.slug,
        payload={"name": category.name, "parent": body.parent},
    )
    db.commit()
    parent_slug = None
    if category.parent_id is not None:
        parent = CatalogService(db)
        for c in parent.list_categories(merchant_id):
            if c.id == category.parent_id:
                parent_slug = c.slug
    return MerchantCategoryItem(
        id=category.id, slug=category.slug, name=category.name, parent_slug=parent_slug
    )


# -- products --------------------------------------------------------


@router.get(
    "/products",
    response_model=MerchantProductListResponse,
    summary="Paginated variant list (includes inactive)",
)
def list_products(
    category: str | None = Query(default=None),
    q: str | None = Query(default=None, max_length=200),
    stock_status: str | None = Query(default=None, pattern="^(IN_STOCK|LOW_STOCK|OUT_OF_STOCK)$"),
    active: bool | None = Query(default=None),
    limit: int = Query(default=25, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: DbSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
    merchant_id: uuid.UUID = Depends(require_merchant_id),
) -> MerchantProductListResponse:
    try:
        page = MerchantCatalogService(db).list_products(
            merchant_id,
            category_slug=category,
            search=q,
            stock_status=stock_status,
            active=active,
            limit=limit,
            offset=offset,
        )
    except MerchantError as error:
        raise _fail(error) from error
    return MerchantProductListResponse.of(page)


@router.get(
    "/products/{product_id}",
    response_model=MerchantProductDetailResponse,
    summary="One product with every variant",
)
def get_product(
    product_id: uuid.UUID,
    db: DbSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
    merchant_id: uuid.UUID = Depends(require_merchant_id),
) -> MerchantProductDetailResponse:
    writer = MerchantCatalogService(db)
    return _detail(CatalogService(db), InventoryService(db), merchant_id, product_id, writer)


@router.post(
    "/products",
    response_model=MerchantProductDetailResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a product (and, optionally, its first variants)",
)
def create_product(
    merchant: CurrentMerchant,
    body: ProductCreateRequest,
    db: DbSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
    merchant_id: uuid.UUID = Depends(require_merchant_id),
) -> MerchantProductDetailResponse:
    writer = MerchantCatalogService(db)
    try:
        detail = writer.create_product(
            merchant_id,
            name=body.name,
            category_slug=body.category,
            description=body.description,
            brand=body.brand,
            attributes=body.attributes,
            tags=body.tags,
            slug=body.slug,
            variants=[v.model_dump() for v in body.variants],
        )
    except MerchantError as error:
        raise _fail(error) from error
    ActivityService(db).record(
        merchant,
        MerchantAction.PRODUCT_CREATED,
        MerchantEntityType.PRODUCT,
        entity_id=detail.product.id,
        subject=detail.product.name,
        payload={
            "slug": detail.product.slug,
            "category": detail.product.category_slug,
            # Prices as strings, here as everywhere (ADR-008).
            "variants": [{"sku": v.sku, "price": str(v.price)} for v in detail.variants],
        },
    )
    db.commit()
    return _detail(
        CatalogService(db),
        InventoryService(db),
        merchant_id,
        detail.product.id,
        writer,
    )


@router.patch(
    "/products/{product_id}",
    response_model=MerchantProductDetailResponse,
    summary="Update a product",
)
def update_product(
    merchant: CurrentMerchant,
    product_id: uuid.UUID,
    body: ProductUpdateRequest,
    db: DbSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
    merchant_id: uuid.UUID = Depends(require_merchant_id),
) -> MerchantProductDetailResponse:
    writer = MerchantCatalogService(db)
    unset = frozenset(
        name
        for name in ("description", "brand")
        if name in body.model_fields_set and getattr(body, name) is None
    )
    try:
        writer.update_product(
            merchant_id,
            product_id,
            name=body.name,
            category_slug=body.category,
            description=body.description,
            brand=body.brand,
            attributes=body.attributes,
            tags=body.tags,
            is_active=body.is_active,
            _unset=unset,
        )
    except MerchantError as error:
        raise _fail(error) from error
    ActivityService(db).record(
        merchant,
        MerchantAction.PRODUCT_UPDATED,
        MerchantEntityType.PRODUCT,
        entity_id=product_id,
        subject=body.name,
        # Only the fields the request actually set — an update that changed a
        # name should not read as though it also confirmed every other value.
        payload={"changed": sorted(body.model_fields_set), "unset": sorted(unset)},
    )
    db.commit()
    return _detail(CatalogService(db), InventoryService(db), merchant_id, product_id, writer)


@router.post(
    "/products/{product_id}/archive",
    response_model=MerchantProductDetailResponse,
    summary="Archive a product (soft delete — order history is preserved)",
)
def archive_product(
    merchant: CurrentMerchant,
    product_id: uuid.UUID,
    db: DbSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
    merchant_id: uuid.UUID = Depends(require_merchant_id),
) -> MerchantProductDetailResponse:
    writer = MerchantCatalogService(db)
    try:
        writer.set_product_active(merchant_id, product_id, active=False)
    except MerchantError as error:
        raise _fail(error) from error
    ActivityService(db).record(
        merchant,
        MerchantAction.PRODUCT_ARCHIVED,
        MerchantEntityType.PRODUCT,
        entity_id=product_id,
    )
    db.commit()
    return _detail(CatalogService(db), InventoryService(db), merchant_id, product_id, writer)


@router.post(
    "/products/{product_id}/restore",
    response_model=MerchantProductDetailResponse,
    summary="Restore an archived product",
)
def restore_product(
    merchant: CurrentMerchant,
    product_id: uuid.UUID,
    db: DbSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
    merchant_id: uuid.UUID = Depends(require_merchant_id),
) -> MerchantProductDetailResponse:
    writer = MerchantCatalogService(db)
    try:
        writer.set_product_active(merchant_id, product_id, active=True)
    except MerchantError as error:
        raise _fail(error) from error
    ActivityService(db).record(
        merchant,
        MerchantAction.PRODUCT_RESTORED,
        MerchantEntityType.PRODUCT,
        entity_id=product_id,
    )
    db.commit()
    return _detail(CatalogService(db), InventoryService(db), merchant_id, product_id, writer)


# -- variants ------------------------------------------------------


@router.post(
    "/products/{product_id}/variants",
    response_model=MerchantProductDetailResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Add a variant to a product",
)
def create_variant(
    merchant: CurrentMerchant,
    product_id: uuid.UUID,
    body: VariantCreateRequest,
    db: DbSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
    merchant_id: uuid.UUID = Depends(require_merchant_id),
) -> MerchantProductDetailResponse:
    writer = MerchantCatalogService(db)
    try:
        writer.create_variant(merchant_id, product_id, body.model_dump())
    except MerchantError as error:
        raise _fail(error) from error
    ActivityService(db).record(
        merchant,
        MerchantAction.VARIANT_CREATED,
        MerchantEntityType.VARIANT,
        entity_id=product_id,
        subject=body.sku,
        payload={"price": body.price, "quantity": body.quantity},
    )
    db.commit()
    return _detail(CatalogService(db), InventoryService(db), merchant_id, product_id, writer)


@router.patch(
    "/variants/{variant_id}",
    response_model=MerchantProductDetailResponse,
    summary="Update a variant (price, name, attributes, active)",
)
def update_variant(
    merchant: CurrentMerchant,
    variant_id: uuid.UUID,
    body: VariantUpdateRequest,
    db: DbSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
    merchant_id: uuid.UUID = Depends(require_merchant_id),
) -> MerchantProductDetailResponse:
    writer = MerchantCatalogService(db)
    # Read the old price before the write: a PRICE_CHANGED entry that cannot say
    # what the price changed *from* answers half the question it exists for.
    before = CatalogService(db).get_variant(merchant_id, variant_id)
    previous_price = None if before is None else str(before.price)
    try:
        detail = writer.update_variant(
            merchant_id,
            variant_id,
            name=body.name,
            price=body.price,
            attributes=body.attributes,
            is_active=body.is_active,
        )
    except MerchantError as error:
        raise _fail(error) from error

    activity = ActivityService(db)
    sku = next((v.sku for v in detail.variants if v.id == variant_id), None)
    if body.price is not None and body.price != previous_price:
        # A price move gets its own action, not a generic "updated": it is the
        # one dashboard edit that changes what a buyer is quoted.
        activity.record(
            merchant,
            MerchantAction.PRICE_CHANGED,
            MerchantEntityType.VARIANT,
            entity_id=variant_id,
            subject=sku,
            payload={"from": previous_price, "to": body.price},
        )
    else:
        activity.record(
            merchant,
            MerchantAction.VARIANT_UPDATED,
            MerchantEntityType.VARIANT,
            entity_id=variant_id,
            subject=sku,
            payload={"changed": sorted(body.model_fields_set)},
        )
    db.commit()
    return _detail(
        CatalogService(db),
        InventoryService(db),
        merchant_id,
        detail.product.id,
        writer,
    )


# -- inventory ---------------------------------------------------


@router.get(
    "/inventory",
    response_model=MerchantProductListResponse,
    summary="Inventory rows, lowest available first",
)
def list_inventory(
    low_only: bool = Query(default=False),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: DbSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
    merchant_id: uuid.UUID = Depends(require_merchant_id),
) -> MerchantProductListResponse:
    page = MerchantCatalogService(db).stock_rows(
        merchant_id, low_only=low_only, limit=limit, offset=offset
    )
    return MerchantProductListResponse.of(page)


@router.patch(
    "/inventory/{variant_id}",
    response_model=MerchantVariantItem,
    summary="Set a variant's on-hand quantity",
)
def set_stock(
    merchant: CurrentMerchant,
    variant_id: uuid.UUID,
    body: StockUpdateRequest,
    db: DbSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
    merchant_id: uuid.UUID = Depends(require_merchant_id),
) -> MerchantVariantItem:
    stock = InventoryService(db).get_stock_map(merchant_id, [variant_id])
    was = stock[variant_id].quantity if variant_id in stock else None
    try:
        row = MerchantCatalogService(db).set_stock(merchant_id, variant_id, quantity=body.quantity)
    except MerchantError as error:
        raise _fail(error) from error
    ActivityService(db).record(
        merchant,
        MerchantAction.STOCK_CHANGED,
        MerchantEntityType.VARIANT,
        entity_id=variant_id,
        subject=row.sku,
        payload={"from": was, "to": body.quantity, "stock_status": row.stock_status.value},
    )
    db.commit()
    return MerchantVariantItem.of(row)


# -- activity log ------------------------------------------------


class MerchantActivityItem(BaseModel):
    """One recorded administrative action."""

    id: uuid.UUID
    seq: int
    action: str
    entity_type: str
    entity_id: uuid.UUID | None = None
    subject: str | None = None
    actor_email: str
    payload: dict = {}
    created_at: str


class MerchantActivityPage(BaseModel):
    items: list[MerchantActivityItem]
    total: int
    limit: int
    offset: int


@router.get(
    "/activity",
    response_model=MerchantActivityPage,
    summary="Who changed what, newest first",
)
def list_activity(
    action: str | None = Query(default=None, max_length=48),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: DbSession = Depends(get_db),
    merchant_id: uuid.UUID = Depends(require_merchant_id),
) -> MerchantActivityPage:
    """Read-only, and scoped to the token's own merchant.

    Ordered by `seq` rather than by timestamp: two edits inside one transaction
    share a `created_at`, and "what happened next" is the question a log is read
    to answer.
    """
    rows, total = ActivityService(db).list_for_merchant(
        merchant_id, action=action, limit=limit, offset=offset
    )
    return MerchantActivityPage(
        items=[
            MerchantActivityItem(
                id=row.id,
                seq=row.seq,
                action=row.action,
                entity_type=row.entity_type,
                entity_id=row.entity_id,
                subject=row.subject,
                actor_email=row.actor_email,
                payload=row.payload,
                created_at=row.created_at.isoformat(),
            )
            for row in rows
        ],
        total=total,
        limit=limit,
        offset=offset,
    )


# -- orders ----------------------------------------------------


def _orders(db: DbSession, settings: Settings) -> OrderService:
    """`OrderService` for the read paths only. `spending_limit` is required by the
    constructor (it builds a Policy Engine for `create_order`), but `list` and
    `get` never touch it — the dashboard observes order state, never drives it."""
    return OrderService(
        db,
        spending_limit=settings.spending_limit,
        spending_limit_currency=settings.spending_limit_currency,
    )


def _order_item(order: Order) -> MerchantOrderItem:
    return MerchantOrderItem(
        order_id=order.id,
        status=order.status,
        currency=order.currency,
        subtotal_amount=str(order.subtotal_amount),
        total_amount=str(order.total_amount),
        cart_version=order.cart_version,
        razorpay_order_id=order.razorpay_order_id,
        created_at=order.created_at.isoformat(),
        items=[
            MerchantOrderLine(
                sku=line.sku,
                product_name=line.product_name,
                variant_name=line.variant_name,
                quantity=line.quantity,
                unit_price=str(line.unit_price),
                line_total=str(line.line_total),
            )
            for line in order.items
        ],
    )


@router.get(
    "/orders", response_model=MerchantOrderPage, summary="Paginated order list, newest first"
)
def list_orders(
    status_filter: str | None = Query(default=None, alias="status"),
    limit: int = Query(default=25, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: DbSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
    merchant_id: uuid.UUID = Depends(require_merchant_id),
) -> MerchantOrderPage:
    rows, total = _orders(db, settings).list_for_merchant(
        merchant_id, status=status_filter, limit=limit, offset=offset
    )
    return MerchantOrderPage(
        items=[_order_item(o) for o in rows], total=total, limit=limit, offset=offset
    )


@router.get(
    "/orders/{order_id}", response_model=MerchantOrderItem, summary="One order with its lines"
)
def get_order(
    order_id: uuid.UUID,
    db: DbSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
    merchant_id: uuid.UUID = Depends(require_merchant_id),
) -> MerchantOrderItem:
    order = _orders(db, settings).get(merchant_id, order_id)
    if order is None:
        raise _not_found(f"no order {order_id} for this merchant")
    return _order_item(order)
