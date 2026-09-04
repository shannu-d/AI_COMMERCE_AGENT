"""Merchant-facing catalog management — the write side the storefront never had.

`CatalogService` and `InventoryService` are read-only by contract ("never
writes, never invents"). The merchant dashboard needs to *create* a product,
change a price, adjust stock. That is a different responsibility, so it is a
different service — the same read/write split the codebase already draws between
`CatalogService` (read) and `CartService` (write).

**Merchant scoping.** Every method takes `merchant_id` as its first argument, and
the route resolves that from `settings.default_merchant_id` server-side — it is
never read from a request body (ADR-002). A product, a variant and a category
are all forced to stay within one merchant by the composite foreign keys the
schema already carries; this service additionally refuses to touch a row whose
`merchant_id` does not match, so a wrong id fails as *not found* rather than
silently succeeding against another catalogue.

**No commerce fact is invented.** The service writes what the merchant supplied,
validated. It never fabricates a SKU, a price or a stock level, and it never
lets a caller set a value the schema would reject — the CHECK constraints are
the backstop, the validation here is the friendly error.

Nothing in this module imports `app.llm` or `app.agent`: it is on the trusted,
deterministic side of the boundary.
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.canonical import is_canonical_token, normalize_token
from app.db.base import SKU_REGEX
from app.db.models import Category, Inventory, Merchant, Order, Product, ProductVariant
from app.domain import ProductDetail, StockStatus, StockView
from app.domain.commerce import OrderStatus
from app.repositories.product_repository import ProductRepository
from app.repositories.variant_repository import VariantQuery, VariantRepository
from app.services._mapping import to_product_summary, to_variant_view
from app.services.catalog_service import CatalogService
from app.services.inventory_service import InventoryService

__all__ = [
    "MerchantAnalyticsService",
    "MerchantCatalogService",
    "MerchantError",
    "MerchantOverview",
    "MerchantProductPage",
    "MerchantProductRow",
]

_SKU_RE = re.compile(SKU_REGEX)
#: Order states that represent money the merchant will actually receive. An
#: order sitting in `ORDER_CREATED` has not been paid; a failed or cancelled one
#: never will be.
_REVENUE_STATES: frozenset[str] = frozenset({OrderStatus.PAYMENT_CONFIRMED.value})
_PLACED_STATES: frozenset[str] = frozenset(
    s.value for s in OrderStatus if s not in {OrderStatus.CANCELLED}
)


class MerchantError(Exception):
    """A merchant action that could not be completed, with a machine code.

    `code` is one of F§25's closed vocabulary where one fits (`VALIDATION_ERROR`,
    `PRODUCT_NOT_FOUND`, `VARIANT_NOT_FOUND`) so the route never has to grow a
    new public error code for the dashboard.
    """

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


# --------------------------------------------------------------------------
# Result shapes (frozen — no live ORM row leaves this module)
# --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class MerchantProductRow:
    """One variant row for the dashboard products/inventory table."""

    product_id: uuid.UUID
    variant_id: uuid.UUID
    product_slug: str
    product_name: str
    variant_name: str
    sku: str
    category: str
    price: Decimal
    currency: str
    quantity: int
    reserved_quantity: int
    available_quantity: int
    stock_status: StockStatus
    product_active: bool
    variant_active: bool
    attributes: dict[str, object]


@dataclass(frozen=True, slots=True)
class MerchantProductPage:
    rows: tuple[MerchantProductRow, ...]
    total: int
    limit: int
    offset: int


@dataclass(frozen=True, slots=True)
class MerchantOverview:
    currency: str
    total_products: int
    active_products: int
    archived_products: int
    total_variants: int
    active_variants: int
    total_inventory_units: int
    out_of_stock_variants: int
    low_stock_variants: int
    category_count: int
    total_orders: int
    paid_orders: int
    revenue: Decimal


# --------------------------------------------------------------------------
# Write service
# --------------------------------------------------------------------------


class MerchantCatalogService:
    """Creates and edits a merchant's catalogue. Validated writes only."""

    def __init__(self, session: Session, *, low_stock_threshold: int | None = None) -> None:
        self._session = session
        self._products = ProductRepository(session)
        self._variants = VariantRepository(session)
        self._catalog = CatalogService(session)
        self._inventory = InventoryService(session, low_stock_threshold=low_stock_threshold)

    # -- reads for the dashboard ------------------------------------------

    def list_products(
        self,
        merchant_id: uuid.UUID,
        *,
        category_slug: str | None = None,
        search: str | None = None,
        stock_status: str | None = None,
        active: bool | None = None,
        limit: int = 25,
        offset: int = 0,
    ) -> MerchantProductPage:
        """A page of the merchant's variants, including inactive ones.

        `stock_status` is filtered here rather than in SQL: inventory is a
        separate concern (ADR-005), and the coarse status is derived from the
        stock map, not stored.
        """
        limit = max(1, min(limit, 100))
        offset = max(0, offset)
        if category_slug is not None and not self._catalog.category_exists(
            merchant_id, category_slug
        ):
            raise MerchantError(
                "VALIDATION_ERROR", f"no category {category_slug!r} for this merchant"
            )

        base_query = VariantQuery(
            category_slug=category_slug,
            search_text=search,
            include_inactive=True,
        )

        # Without a stock filter the count is exact and paging happens in SQL.
        if stock_status is None and active is None:
            total = self._variants.count(merchant_id, base_query)
            rows = self._variants.search(
                merchant_id,
                VariantQuery(
                    category_slug=category_slug,
                    search_text=search,
                    include_inactive=True,
                    limit=limit,
                    offset=offset,
                ),
            )
            page = [self._row(merchant_id, v) for v in rows]
            return MerchantProductPage(tuple(page), total, limit, offset)

        # With a stock/active filter, load the filtered set and page in memory —
        # a merchant catalogue is thousands of rows at most.
        all_rows = self._variants.search(merchant_id, base_query)
        materialised = [self._row(merchant_id, v) for v in all_rows]
        if stock_status is not None:
            want = stock_status.upper()
            materialised = [r for r in materialised if r.stock_status.value == want]
        if active is not None:
            materialised = [r for r in materialised if r.variant_active == active]
        total = len(materialised)
        return MerchantProductPage(
            tuple(materialised[offset : offset + limit]), total, limit, offset
        )

    def get_product(self, merchant_id: uuid.UUID, product_id: uuid.UUID) -> ProductDetail:
        product = self._products.get(merchant_id, product_id, include_inactive=True)
        if product is None:
            raise MerchantError("PRODUCT_NOT_FOUND", f"no product {product_id} for this merchant")
        variants = self._variants.for_products(merchant_id, [product.id], include_inactive=True)
        return ProductDetail(
            product=to_product_summary(product),
            variants=tuple(to_variant_view(v) for v in variants),
        )

    def stock_rows(
        self, merchant_id: uuid.UUID, *, low_only: bool = False, limit: int = 50, offset: int = 0
    ) -> MerchantProductPage:
        page = self.list_products(merchant_id, limit=10_000, offset=0)
        rows = [r for r in page.rows if not low_only or r.stock_status is not StockStatus.IN_STOCK]
        rows.sort(key=lambda r: (r.available_quantity, r.sku))
        limit = max(1, min(limit, 200))
        return MerchantProductPage(tuple(rows[offset : offset + limit]), len(rows), limit, offset)

    # -- product writes -------------------------------------------------

    def create_product(
        self,
        merchant_id: uuid.UUID,
        *,
        name: str,
        category_slug: str,
        description: str | None = None,
        brand: str | None = None,
        attributes: Mapping[str, object] | None = None,
        tags: Sequence[str] | None = None,
        slug: str | None = None,
        variants: Sequence[Mapping[str, object]] = (),
    ) -> ProductDetail:
        """Create a product and, optionally, its first variants + inventory.

        Everything is validated and resolved before a single row is written, so
        a payload with one bad SKU leaves the catalogue untouched.
        """
        name = _require_text("name", name, 255)
        category = self._products.get_category_by_slug(merchant_id, category_slug)
        if category is None:
            raise MerchantError(
                "VALIDATION_ERROR", f"no category {category_slug!r} for this merchant"
            )

        product_slug = self._resolve_product_slug(merchant_id, slug, name)
        parsed_variants = [self._parse_variant(v, index=i) for i, v in enumerate(variants)]
        seen: set[str] = set()
        for v in parsed_variants:
            if v.sku in seen:
                raise MerchantError(
                    "VALIDATION_ERROR", f"SKU {v.sku!r} is repeated in this request"
                )
            seen.add(v.sku)
            if self._variants.get_by_sku(merchant_id, v.sku, include_inactive=True) is not None:
                raise MerchantError(
                    "VALIDATION_ERROR", f"SKU {v.sku!r} already exists for this merchant"
                )

        product = Product(
            id=uuid.uuid4(),
            merchant_id=merchant_id,
            category_id=category.id,
            name=name,
            slug=product_slug,
            description=_optional_text("description", description, 4000),
            brand=_optional_text("brand", brand, 128),
            attributes=_clean_attributes(attributes),
            tags=_clean_tags(tags),
            is_active=True,
        )
        self._session.add(product)
        self._session.flush()

        for v in parsed_variants:
            self._insert_variant(merchant_id, product.id, v)
        self._session.flush()

        return self.get_product(merchant_id, product.id)

    def update_product(
        self,
        merchant_id: uuid.UUID,
        product_id: uuid.UUID,
        *,
        name: str | None = None,
        category_slug: str | None = None,
        description: str | None = None,
        brand: str | None = None,
        attributes: Mapping[str, object] | None = None,
        tags: Sequence[str] | None = None,
        is_active: bool | None = None,
        _unset: frozenset[str] = frozenset(),
    ) -> ProductDetail:
        """Patch a product. Only the fields passed are changed.

        `_unset` names fields the caller explicitly cleared to `null` (the route
        distinguishes "not sent" from "sent as null"), so a description can be
        removed as well as replaced.
        """
        product = self._products.get(merchant_id, product_id, include_inactive=True)
        if product is None:
            raise MerchantError("PRODUCT_NOT_FOUND", f"no product {product_id} for this merchant")

        if name is not None:
            product.name = _require_text("name", name, 255)
        if category_slug is not None:
            category = self._products.get_category_by_slug(merchant_id, category_slug)
            if category is None:
                raise MerchantError(
                    "VALIDATION_ERROR", f"no category {category_slug!r} for this merchant"
                )
            product.category_id = category.id
        if description is not None or "description" in _unset:
            product.description = _optional_text("description", description, 4000)
        if brand is not None or "brand" in _unset:
            product.brand = _optional_text("brand", brand, 128)
        if attributes is not None:
            product.attributes = _clean_attributes(attributes)
        if tags is not None:
            product.tags = _clean_tags(tags)
        if is_active is not None:
            product.is_active = is_active

        self._session.flush()
        return self.get_product(merchant_id, product.id)

    def set_product_active(
        self, merchant_id: uuid.UUID, product_id: uuid.UUID, *, active: bool
    ) -> ProductDetail:
        """Archive (or restore) a product. This is the only 'delete' the
        dashboard offers — an order line references a variant with `RESTRICT`,
        so a sold product's rows must never be hard-deleted."""
        return self.update_product(merchant_id, product_id, is_active=active)

    # -- variant writes ------------------------------------------------

    def create_variant(
        self, merchant_id: uuid.UUID, product_id: uuid.UUID, payload: Mapping[str, object]
    ) -> ProductDetail:
        product = self._products.get(merchant_id, product_id, include_inactive=True)
        if product is None:
            raise MerchantError("PRODUCT_NOT_FOUND", f"no product {product_id} for this merchant")
        parsed = self._parse_variant(payload, index=0)
        if self._variants.get_by_sku(merchant_id, parsed.sku, include_inactive=True) is not None:
            raise MerchantError(
                "VALIDATION_ERROR", f"SKU {parsed.sku!r} already exists for this merchant"
            )
        self._insert_variant(merchant_id, product.id, parsed)
        self._session.flush()
        return self.get_product(merchant_id, product.id)

    def update_variant(
        self,
        merchant_id: uuid.UUID,
        variant_id: uuid.UUID,
        *,
        name: str | None = None,
        price: str | Decimal | None = None,
        attributes: Mapping[str, object] | None = None,
        is_active: bool | None = None,
    ) -> ProductDetail:
        variant = self._variants.get(merchant_id, variant_id, include_inactive=True)
        if variant is None:
            raise MerchantError("VARIANT_NOT_FOUND", f"no variant {variant_id} for this merchant")

        if name is not None:
            variant.name = _require_text("name", name, 255)
        if price is not None:
            variant.price = _parse_price(price)
        if attributes is not None:
            variant.attributes = _clean_attributes(attributes)
        if is_active is not None:
            variant.is_active = is_active

        self._session.flush()
        return self.get_product(merchant_id, variant.product_id)

    def set_stock(
        self, merchant_id: uuid.UUID, variant_id: uuid.UUID, *, quantity: int
    ) -> MerchantProductRow:
        """Set a variant's on-hand quantity. Goes through the schema's CHECK
        constraints (`quantity >= 0`, `reserved <= quantity`), never around them."""
        if not isinstance(quantity, int) or isinstance(quantity, bool) or quantity < 0:
            raise MerchantError(
                "VALIDATION_ERROR", "quantity must be a whole number of zero or more"
            )
        if quantity > 1_000_000:
            raise MerchantError("VALIDATION_ERROR", "quantity is implausibly large")

        variant = self._variants.get(merchant_id, variant_id, include_inactive=True)
        if variant is None:
            raise MerchantError("VARIANT_NOT_FOUND", f"no variant {variant_id} for this merchant")

        row = self._session.execute(
            select(Inventory)
            .join(ProductVariant, ProductVariant.id == Inventory.variant_id)
            .where(Inventory.variant_id == variant_id, ProductVariant.merchant_id == merchant_id)
        ).scalar_one_or_none()
        if row is None:
            row = Inventory(
                id=uuid.uuid4(), variant_id=variant_id, quantity=quantity, reserved_quantity=0
            )
            self._session.add(row)
        else:
            if quantity < row.reserved_quantity:
                raise MerchantError(
                    "VALIDATION_ERROR",
                    f"quantity {quantity} is below the {row.reserved_quantity} already reserved",
                )
            row.quantity = quantity
        self._session.flush()
        return self._row(merchant_id, variant)

    # -- category writes ---------------------------------------------

    def create_category(
        self,
        merchant_id: uuid.UUID,
        *,
        name: str,
        slug: str | None = None,
        parent_slug: str | None = None,
    ) -> Category:
        name = _require_text("name", name, 255)
        resolved = normalize_token(slug) if slug else normalize_token(name)
        if not resolved or not is_canonical_token(resolved):
            raise MerchantError("VALIDATION_ERROR", "slug must be a lowercase token")
        if self._products.get_category_by_slug(merchant_id, resolved) is not None:
            raise MerchantError("VALIDATION_ERROR", f"category {resolved!r} already exists")

        parent_id: uuid.UUID | None = None
        if parent_slug is not None:
            parent = self._products.get_category_by_slug(merchant_id, parent_slug)
            if parent is None:
                raise MerchantError("VALIDATION_ERROR", f"no parent category {parent_slug!r}")
            parent_id = parent.id

        category = Category(
            id=uuid.uuid4(),
            merchant_id=merchant_id,
            name=name,
            slug=resolved,
            parent_id=parent_id,
        )
        self._session.add(category)
        self._session.flush()
        return category

    # -- internals -------------------------------------------------

    @dataclass(frozen=True, slots=True)
    class _ParsedVariant:
        sku: str
        name: str
        price: Decimal
        quantity: int
        attributes: dict[str, object]

    def _parse_variant(self, payload: Mapping[str, object], *, index: int) -> _ParsedVariant:
        if not isinstance(payload, Mapping):
            raise MerchantError("VALIDATION_ERROR", f"variant {index} is not an object")
        sku_raw = payload.get("sku")
        if not isinstance(sku_raw, str) or not _SKU_RE.match(sku_raw):
            raise MerchantError(
                "VALIDATION_ERROR",
                f"variant {index}: SKU must be uppercase letters, digits, '-' and '_'",
            )
        if len(sku_raw) > 64:
            raise MerchantError("VALIDATION_ERROR", f"variant {index}: SKU is too long")
        name = _require_text(f"variant {index} name", payload.get("name"), 255)
        price = _parse_price(payload.get("price"))
        quantity = payload.get("quantity", 0)
        if not isinstance(quantity, int) or isinstance(quantity, bool) or quantity < 0:
            raise MerchantError("VALIDATION_ERROR", f"variant {index}: quantity must be >= 0")
        return self._ParsedVariant(
            sku=sku_raw,
            name=name,
            price=price,
            quantity=quantity,
            attributes=_clean_attributes(payload.get("attributes")),
        )

    def _merchant_currency(self, merchant_id: uuid.UUID) -> str:
        """The merchant's own currency — a new variant is priced in it. Read from
        the `merchants` row, not a global constant, so this module stays clear of
        `app.llm` (the deterministic-side import boundary)."""
        currency = self._session.execute(
            select(Merchant.currency).where(Merchant.id == merchant_id)
        ).scalar_one_or_none()
        if currency is None:
            raise MerchantError("VALIDATION_ERROR", "unknown merchant")
        return currency

    def _insert_variant(
        self, merchant_id: uuid.UUID, product_id: uuid.UUID, parsed: _ParsedVariant
    ) -> ProductVariant:
        variant = ProductVariant(
            id=uuid.uuid4(),
            merchant_id=merchant_id,
            product_id=product_id,
            sku=parsed.sku,
            name=parsed.name,
            price=parsed.price,
            currency=self._merchant_currency(merchant_id),
            attributes=parsed.attributes,
            is_active=True,
        )
        self._session.add(variant)
        self._session.flush()
        self._session.add(
            Inventory(
                id=uuid.uuid4(),
                variant_id=variant.id,
                quantity=parsed.quantity,
                reserved_quantity=0,
            )
        )
        return variant

    def _resolve_product_slug(self, merchant_id: uuid.UUID, slug: str | None, name: str) -> str:
        candidate = normalize_token(slug) if slug else normalize_token(name)
        if not candidate or not is_canonical_token(candidate):
            raise MerchantError("VALIDATION_ERROR", "slug must be a lowercase token")
        if len(candidate) > 160:
            candidate = candidate[:160].rstrip("_-")
        # Auto-disambiguate a generated slug; reject an explicit collision.
        if self._products.get_by_slug(merchant_id, candidate, include_inactive=True) is None:
            return candidate
        if slug:
            raise MerchantError("VALIDATION_ERROR", f"product slug {candidate!r} already exists")
        for n in range(2, 100):
            alt = f"{candidate}_{n}"
            if self._products.get_by_slug(merchant_id, alt, include_inactive=True) is None:
                return alt
        raise MerchantError("VALIDATION_ERROR", "could not derive a unique product slug")

    def _row(self, merchant_id: uuid.UUID, variant: ProductVariant) -> MerchantProductRow:
        view = to_variant_view(variant)
        stock = self._inventory.get_stock(merchant_id, variant.id)
        return MerchantProductRow(
            product_id=view.product_id,
            variant_id=view.id,
            product_slug=view.product_slug,
            product_name=view.product_name,
            variant_name=view.name,
            sku=view.sku,
            category=view.category_slug,
            price=view.price,
            currency=view.currency,
            quantity=stock.quantity,
            reserved_quantity=stock.reserved_quantity,
            available_quantity=stock.available_quantity,
            stock_status=stock.status,
            product_active=view.product_is_active,
            variant_active=view.is_active,
            attributes=view.merged_attributes,
        )


# --------------------------------------------------------------------------
# Analytics — real aggregates, no fabricated numbers
# --------------------------------------------------------------------------


class MerchantAnalyticsService:
    """Dashboard metrics, each derived directly from the source tables."""

    def __init__(self, session: Session, *, low_stock_threshold: int | None = None) -> None:
        self._session = session
        self._inventory = InventoryService(session, low_stock_threshold=low_stock_threshold)
        self._catalog = CatalogService(session)

    def overview(self, merchant_id: uuid.UUID, *, currency: str = "INR") -> MerchantOverview:
        s = self._session

        total_products = s.execute(
            select(func.count()).select_from(Product).where(Product.merchant_id == merchant_id)
        ).scalar_one()
        active_products = s.execute(
            select(func.count())
            .select_from(Product)
            .where(Product.merchant_id == merchant_id, Product.is_active.is_(True))
        ).scalar_one()

        total_variants = s.execute(
            select(func.count())
            .select_from(ProductVariant)
            .where(ProductVariant.merchant_id == merchant_id)
        ).scalar_one()
        active_variants = s.execute(
            select(func.count())
            .select_from(ProductVariant)
            .join(Product, Product.id == ProductVariant.product_id)
            .where(
                ProductVariant.merchant_id == merchant_id,
                ProductVariant.is_active.is_(True),
                Product.is_active.is_(True),
            )
        ).scalar_one()

        variant_ids = list(
            s.execute(
                select(ProductVariant.id).where(ProductVariant.merchant_id == merchant_id)
            ).scalars()
        )
        stock: dict[uuid.UUID, StockView] = self._inventory.get_stock_map(merchant_id, variant_ids)
        total_units = sum(v.available_quantity for v in stock.values())
        out_of_stock = sum(1 for v in stock.values() if v.status is StockStatus.OUT_OF_STOCK)
        low_stock = sum(1 for v in stock.values() if v.status is StockStatus.LOW_STOCK)

        category_count = len(self._catalog.list_categories(merchant_id))

        total_orders = s.execute(
            select(func.count())
            .select_from(Order)
            .where(Order.merchant_id == merchant_id, Order.status.in_(_PLACED_STATES))
        ).scalar_one()
        paid_orders = s.execute(
            select(func.count())
            .select_from(Order)
            .where(Order.merchant_id == merchant_id, Order.status.in_(_REVENUE_STATES))
        ).scalar_one()
        revenue = s.execute(
            select(func.coalesce(func.sum(Order.total_amount), 0)).where(
                Order.merchant_id == merchant_id, Order.status.in_(_REVENUE_STATES)
            )
        ).scalar_one()

        return MerchantOverview(
            currency=currency,
            total_products=int(total_products),
            active_products=int(active_products),
            archived_products=int(total_products) - int(active_products),
            total_variants=int(total_variants),
            active_variants=int(active_variants),
            total_inventory_units=int(total_units),
            out_of_stock_variants=int(out_of_stock),
            low_stock_variants=int(low_stock),
            category_count=category_count,
            total_orders=int(total_orders),
            paid_orders=int(paid_orders),
            revenue=Decimal(revenue).quantize(Decimal("0.01")),
        )


# --------------------------------------------------------------------------
# Shared validation helpers
# --------------------------------------------------------------------------


def _require_text(label: str, value: object, max_len: int) -> str:
    if not isinstance(value, str) or not value.strip():
        raise MerchantError("VALIDATION_ERROR", f"{label} is required")
    text = value.strip()
    if len(text) > max_len:
        raise MerchantError("VALIDATION_ERROR", f"{label} is too long (max {max_len})")
    return text


def _optional_text(label: str, value: object, max_len: int) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise MerchantError("VALIDATION_ERROR", f"{label} must be text")
    text = value.strip()
    if not text:
        return None
    if len(text) > max_len:
        raise MerchantError("VALIDATION_ERROR", f"{label} is too long (max {max_len})")
    return text


def _parse_price(value: object) -> Decimal:
    """A price is a string with at most two decimal places (ADR-008). A JSON
    number is refused — it would already have been through `float`."""
    if isinstance(value, bool) or not isinstance(value, str):
        raise MerchantError(
            "VALIDATION_ERROR", 'price must be a decimal string such as "1499.00", not a number'
        )
    try:
        amount = Decimal(value)
    except InvalidOperation:
        raise MerchantError("VALIDATION_ERROR", f"price {value!r} is not a decimal") from None
    if amount.is_nan() or amount.is_infinite() or amount < 0:
        raise MerchantError("VALIDATION_ERROR", "price must be zero or more")
    if -amount.as_tuple().exponent > 2:
        raise MerchantError("VALIDATION_ERROR", "price has more than two decimal places")
    if amount > Decimal("10000000.00"):
        raise MerchantError("VALIDATION_ERROR", "price is implausibly large")
    return amount


def _clean_attributes(value: object) -> dict[str, object]:
    """A flat object of string/number/bool values — the shape both the ranking
    engine and the JSONB CHECK constraint expect."""
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise MerchantError("VALIDATION_ERROR", "attributes must be an object")
    cleaned: dict[str, object] = {}
    for key, val in value.items():
        if not isinstance(key, str) or not key.strip():
            raise MerchantError("VALIDATION_ERROR", "attribute keys must be non-empty strings")
        if isinstance(val, bool) or isinstance(val, (str, int, float)):
            cleaned[key.strip()] = val
        elif val is None:
            continue
        else:
            raise MerchantError(
                "VALIDATION_ERROR",
                f"attribute {key!r} must be a string, number or boolean",
            )
    return cleaned


def _clean_tags(value: object) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, (list, tuple)):
        raise MerchantError("VALIDATION_ERROR", "tags must be a list")
    tags: list[str] = []
    for tag in value:
        if not isinstance(tag, str) or not tag.strip():
            raise MerchantError("VALIDATION_ERROR", "each tag must be a non-empty string")
        cleaned = tag.strip()
        if len(cleaned) > 64:
            raise MerchantError("VALIDATION_ERROR", f"tag {cleaned!r} is too long")
        if cleaned not in tags:
            tags.append(cleaned)
    return tags
