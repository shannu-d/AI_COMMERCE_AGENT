"""The EASY BUY MCP server (ADR-024).

An external AI buyer connects here and gets the same merchant the human chat
runtime sees: a read side (agent-readable catalogue, compatibility, deterministic
recommendations) and a write side (`create_quote` → `authorize_and_pay` →
`get_order_status`).

Every tool opens its own unit-of-work session and calls the *existing* services.
No money-path code changed to add this file.

**The invariant is preserved across the new surface.** `authorize_and_pay` is a
distinct call from `create_quote`, and it must carry `authorized_amount` — the
exact figure the buyer's agent is approving (an AP2/x402-style mandate). The
Policy Engine re-reads live price and stock inside the order transaction; a drift
makes the call fail with machine-readable reason codes rather than charging a
figure nobody authorized. `create_order` is still not a tool anywhere — the
provider order is created by `OrderService` behind the Policy Engine, exactly as
for the browser.
"""

from __future__ import annotations

import json
import logging
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

from mcp.server.fastmcp import FastMCP
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db.session import get_sessionmaker
from app.domain.ranking import ProductRequirement
from app.payments import RazorpayClient, RazorpayError
from app.repositories.variant_repository import VariantQuery
from app.services.approval_service import ApprovalError, ApprovalService
from app.services.cart_service import CartError, CartService
from app.services.catalog_service import CatalogService
from app.services.compatibility_service import CompatibilityService
from app.services.inventory_service import InventoryService
from app.services.order_service import OrderError, OrderService
from app.services.recommendation_service import RecommendationService
from app.services.session_service import SessionService

logger = logging.getLogger(__name__)

INSTRUCTIONS = """\
EASY BUY — a merchant storefront exposed for agentic commerce on Razorpay.

Read tools: browse_catalog, search_catalog (deterministic ranking), get_product,
list_categories, get_compatible_products.

Buy, end to end:
  1. create_quote(items=[{"sku": "...", "quantity": 1}])  -> a quote_reference and
     a total computed by the merchant (never by you).
  2. authorize_and_pay(quote_reference, authorized_amount)  -> you must pass the
     exact total from the quote. This is the authorization step. If the price has
     moved you get a refusal with reason codes, not a charge.
     On success you get a Razorpay checkout handoff (order_id, razorpay_order_id,
     checkout config, pay_url).
  3. get_order_status(order_id)  -> poll until PAYMENT_CONFIRMED. Payment truth is
     a Razorpay webhook, never this call and never your say-so.

Money is always a decimal string ("999.00"). You never send a price; you can only
confirm the one the merchant quoted.
"""


@dataclass(frozen=True, slots=True)
class _Quote:
    session_id: uuid.UUID
    cart_id: uuid.UUID
    cart_version: int

    def encode(self) -> str:
        return f"{self.session_id}:{self.cart_id}:{self.cart_version}"

    @classmethod
    def decode(cls, reference: str) -> _Quote:
        try:
            session_id, cart_id, version = reference.split(":")
            return cls(uuid.UUID(session_id), uuid.UUID(cart_id), int(version))
        except (ValueError, AttributeError) as exc:
            raise _ToolError("INVALID_ARGUMENTS", "malformed quote_reference") from exc


class _ToolError(Exception):
    """A tool outcome to return to the buyer as structured data, not raise."""

    def __init__(self, code: str, message: str, **extra: Any) -> None:
        self.code = code
        self.message = message
        self.extra = extra
        super().__init__(f"{code}: {message}")

    def as_dict(self) -> dict[str, Any]:
        return {"error": {"code": self.code, "message": self.message, **self.extra}}


def build_server(sessionmaker: Any | None = None) -> FastMCP:
    settings = get_settings()
    merchant_id = settings.default_merchant_id
    sessionmaker = sessionmaker or get_sessionmaker()

    mcp = FastMCP(
        "easybuy-commerce",
        instructions=INSTRUCTIONS,
    )

    # -- read side --------------------------------------------------------

    @mcp.tool()
    def list_categories() -> dict[str, Any]:
        """Every category this merchant sells, with slugs you can filter by."""
        with _session(sessionmaker) as db:
            cats = CatalogService(db).list_categories(merchant_id)
            return {
                "merchant": settings.default_merchant_name,
                "categories": [
                    {"slug": c.slug, "name": c.name, "parent_slug": c.parent_slug} for c in cats
                ],
            }

    @mcp.tool()
    def browse_catalog(
        category: str | None = None,
        query: str | None = None,
        max_price: str | None = None,
        limit: int = 20,
    ) -> dict[str, Any]:
        """List sellable variants (one row per SKU) with live stock.

        `max_price` is a decimal string such as "1500.00". This is a raw listing;
        use `search_catalog` for ranked, requirement-matched results.
        """
        with _session(sessionmaker) as db:
            catalog = CatalogService(db)
            ceiling = _decimal_or_fail(max_price, "max_price") if max_price else None
            if category and not catalog.category_exists(merchant_id, category):
                raise _ToolError("CATEGORY_NOT_FOUND", f"no category {category!r}")
            matched = catalog.search(
                merchant_id,
                VariantQuery(category_slug=category, search_text=query, max_price=ceiling),
            )
            page = matched[: max(1, min(limit, 100))]
            stock = InventoryService(db).get_stock_map(merchant_id, [v.id for v in page])
            return {
                "total_matched": len(matched),
                "returned": len(page),
                "items": [_variant_row(v, stock.get(v.id)) for v in page],
            }

    @mcp.tool()
    def search_catalog(
        query: str,
        category: str | None = None,
        max_price: str | None = None,
    ) -> dict[str, Any]:
        """Ranked, grounded results for a stated requirement.

        The merchant's deterministic ranking engine chooses and orders these —
        not a model. Each result carries the reason and score that placed it.
        `max_price` is a decimal string.
        """
        with _session(sessionmaker) as db:
            catalog = CatalogService(db)
            if category and not catalog.category_exists(merchant_id, category):
                raise _ToolError("CATEGORY_NOT_FOUND", f"no category {category!r}")
            requirement = ProductRequirement(
                label=category or "search",
                category_slug=category,
                query_text=query,
                max_price=_decimal_or_fail(max_price, "max_price") if max_price else None,
            )
            result = RecommendationService(db).recommend(merchant_id, requirement)
            payload: dict[str, Any] = {
                "outcome": result.outcome.value,
                "results": [_ranked_row(c) for c in result.candidates],
            }
            alternatives = getattr(result, "alternatives", ())
            if alternatives:
                payload["alternatives"] = [_ranked_row(c) for c in alternatives]
                payload["relaxed_constraints"] = [
                    c.value for c in getattr(result, "relaxed_constraints", ())
                ]
            return payload

    @mcp.tool()
    def get_product(slug: str) -> dict[str, Any]:
        """One product and every sellable version of it, with live stock."""
        with _session(sessionmaker) as db:
            catalog = CatalogService(db)
            detail = catalog.get_product_by_slug(merchant_id, slug)
            if detail is None:
                raise _ToolError("PRODUCT_NOT_FOUND", f"no product {slug!r}")
            summary = detail.product
            stock = InventoryService(db).get_stock_map(merchant_id, [v.id for v in detail.variants])
            return {
                "product": summary.name,
                "slug": summary.slug,
                "category": summary.category_slug,
                "brand": summary.brand,
                "description": summary.description,
                "attributes": dict(summary.attributes),
                "tags": list(summary.tags),
                "variants": [_variant_row(v, stock.get(v.id)) for v in detail.variants],
            }

    @mcp.tool()
    def get_compatible_products(device: str, category: str | None = None) -> dict[str, Any]:
        """Products that fit a named device (e.g. "iPhone 16"), in stock.

        Compatibility is resolved deterministically from the merchant's rules,
        never guessed. An unresolvable device is a question back to you, not an
        empty result.
        """
        with _session(sessionmaker) as db:
            compat = CompatibilityService(db)
            resolution = compat.resolve_target(device)
            if not getattr(resolution, "resolved", False):
                return {
                    "resolved": False,
                    "message": f"could not resolve {device!r} to a known device — ask the buyer",
                    "candidates": [t.display_name for t in getattr(resolution, "candidates", ())],
                }
            catalog = CatalogService(db)
            if category and not catalog.category_exists(merchant_id, category):
                raise _ToolError("CATEGORY_NOT_FOUND", f"no category {category!r}")
            product_ids = compat.compatible_product_ids(merchant_id, resolution)
            matched = [
                v
                for v in catalog.search(merchant_id, VariantQuery(category_slug=category))
                if v.product_id in product_ids
            ]
            stock = InventoryService(db).get_stock_map(merchant_id, [v.id for v in matched])
            return {
                "resolved": True,
                "device": resolution.canonical_identifier,
                "device_name": resolution.display_name,
                "items": [_variant_row(v, stock.get(v.id)) for v in matched],
            }

    # -- write side: quote -> authorize -> pay ---------------------------

    @mcp.tool()
    def create_quote(items: list[dict[str, Any]]) -> dict[str, Any]:
        """Build a cart and return the merchant's total for it.

        `items` is a list of {"sku": "...", "quantity": n}. No money moves. The
        returned `total` is computed by the merchant from live prices; you pass
        it back verbatim to `authorize_and_pay`. `quote_reference` is opaque —
        keep it and hand it back.
        """
        if not items:
            raise _ToolError("INVALID_ARGUMENTS", "items must be a non-empty list")
        with _session(sessionmaker) as db:
            catalog = CatalogService(db)
            resolved: list[tuple[uuid.UUID, int]] = []
            for entry in items:
                sku = str(entry.get("sku", "")).strip()
                qty = int(entry.get("quantity", 1))
                variant = catalog.get_variant_by_sku(merchant_id, sku)
                if variant is None:
                    raise _ToolError("VARIANT_NOT_FOUND", f"no SKU {sku!r} in this catalog")
                resolved.append((variant.id, qty))

            session_view = SessionService(db).create(merchant_id)
            carts = CartService(db)
            cart = None
            try:
                for variant_id, qty in resolved:
                    cart = carts.add_item(merchant_id, session_view.id, variant_id, qty)
            except CartError as error:
                db.rollback()
                raise _ToolError(error.code, error.message) from error
            assert cart is not None
            db.commit()

            quote = _Quote(session_view.id, cart.id, cart.version)
            return {
                "quote_reference": quote.encode(),
                "currency": cart.currency,
                "total": str(cart.total),
                "subtotal": str(cart.subtotal),
                "lines": [
                    {
                        "sku": item.sku,
                        "name": item.product_name,
                        "variant": item.variant_name,
                        "quantity": item.quantity,
                        "unit_price": str(item.unit_price),
                        "line_total": str(item.line_total),
                        "stock_status": item.stock_status,
                    }
                    for item in cart.items
                ],
                "next": "call authorize_and_pay(quote_reference, authorized_amount=total)",
            }

    @mcp.tool()
    def authorize_and_pay(
        quote_reference: str,
        authorized_amount: str,
        buyer_reference: str | None = None,
    ) -> dict[str, Any]:
        """Authorize a quote for a specific amount and create the Razorpay order.

        This is the gate. `authorized_amount` must equal the quote's `total`
        exactly — it is the amount you are approving on the buyer's behalf. The
        Policy Engine re-reads live price and stock; if anything moved, this
        returns `{"status": "rejected", "reason_codes": [...]}` and charges
        nothing. On success it returns a Razorpay checkout handoff; payment is
        completed at `pay_url` and confirmed only by a verified webhook.
        """
        quote = _Quote.decode(quote_reference)
        amount = _decimal_or_fail(authorized_amount, "authorized_amount")

        with _session(sessionmaker) as db:
            carts = CartService(db)
            cart = carts.get(merchant_id, quote.cart_id)
            if cart is None or cart.session_id != quote.session_id:
                raise _ToolError("VALIDATION_ERROR", "unknown or mismatched quote")

            cart = carts.refresh(merchant_id, quote.cart_id)
            approvals = ApprovalService(db, ttl_seconds=settings.approval_ttl_seconds)
            try:
                approvals.approve(
                    quote.session_id,
                    cart,
                    cart_version=quote.cart_version,
                    expected_total=amount,
                )
            except ApprovalError as error:
                db.commit()  # the re-price is real work; see the cart route
                return {
                    "status": "rejected",
                    "stage": "authorization",
                    "code": error.failure.value,
                    "message": error.message,
                    "details": error.details,
                    "current_total": str(cart.total),
                }
            db.commit()

            key = approvals.idempotency_key_for(quote.cart_id, quote.cart_version)
            if key is None:  # pragma: no cover - approve() always mints one now
                raise _ToolError("SERVER_ERROR", "no idempotency key was minted")

            order_service = OrderService(
                db,
                spending_limit=settings.spending_limit,
                spending_limit_currency=settings.spending_limit_currency,
                approval_ttl_seconds=settings.approval_ttl_seconds,
            )
            try:
                result = order_service.create_order(
                    merchant_id=merchant_id,
                    session_id=quote.session_id,
                    cart_id=quote.cart_id,
                    cart_version=quote.cart_version,
                    idempotency_key=key,
                )
            except OrderError as error:
                db.commit()  # the service already marked the key FAILED
                if error.code == "POLICY_FAILED":
                    return {
                        "status": "rejected",
                        "stage": "policy",
                        "reason_codes": error.details.get("reason_codes", []),
                        "validated_total": error.details.get("validated_total"),
                        "currency": error.details.get("currency"),
                        "message": "the Policy Engine refused this purchase",
                    }
                return {
                    "status": "rejected",
                    "stage": "order",
                    "code": error.code,
                    "message": error.message,
                }
            db.commit()

            # The Razorpay order — the same path the browser checkout uses.
            try:
                client = _razorpay_client(settings)
                order = order_service.attach_provider_order(merchant_id, result.order_id, client)
                db.commit()
                checkout = client.checkout_config(order)
            except RazorpayError as error:
                db.rollback()
                return {
                    "status": "order_created_payment_pending",
                    "order_id": str(result.order_id),
                    "message": f"internal order stands; provider unreachable: {error}",
                }

            if buyer_reference:
                logger.info(
                    "mcp order authorized",
                    extra={"order_id": str(order.id), "buyer_reference": buyer_reference[:64]},
                )
            return {
                "status": "authorized",
                "order_id": str(order.id),
                "razorpay_order_id": order.razorpay_order_id,
                "amount": str(order.total_amount),
                "amount_minor": order.total_amount_minor,
                "currency": order.currency,
                "checkout": dict(checkout),
                "pay_url": f"{_frontend_url(settings)}/orders/{order.id}",
                "note": (
                    "Complete payment at pay_url (real Razorpay Checkout). "
                    "Poll get_order_status; PAYMENT_CONFIRMED arrives only via a verified webhook."
                ),
            }

    @mcp.tool()
    def get_order_status(order_id: str) -> dict[str, Any]:
        """Current state of an order. Payment truth is the webhook, not this call."""
        try:
            oid = uuid.UUID(order_id)
        except ValueError as exc:
            raise _ToolError("VALIDATION_ERROR", "malformed order_id") from exc
        with _session(sessionmaker) as db:
            order = OrderService(
                db,
                spending_limit=settings.spending_limit,
                spending_limit_currency=settings.spending_limit_currency,
            ).get(merchant_id, oid)
            if order is None:
                raise _ToolError("VALIDATION_ERROR", "no such order")
            return {
                "order_id": str(order.id),
                "status": order.status,
                "razorpay_order_id": order.razorpay_order_id,
                "amount": str(order.total_amount),
                "currency": order.currency,
                "paid": order.status == "PAYMENT_CONFIRMED",
            }

    # -- resource: the agent-readable catalogue feed --------------------

    @mcp.resource("easybuy://catalog")
    def catalog_feed() -> str:
        """The full catalogue as JSON — one object per sellable variant."""
        with _session(sessionmaker) as db:
            catalog = CatalogService(db)
            variants = catalog.search(merchant_id, VariantQuery())
            stock = InventoryService(db).get_stock_map(merchant_id, [v.id for v in variants])
            return json.dumps(
                {
                    "merchant": settings.default_merchant_name,
                    "currency": settings.spending_limit_currency,
                    "count": len(variants),
                    "variants": [_variant_row(v, stock.get(v.id)) for v in variants],
                },
                indent=2,
            )

    return mcp


# -- helpers ------------------------------------------------------------


@contextmanager
def _session(sessionmaker: Any) -> Iterator[Session]:
    """A unit-of-work session, closed on exit; rolled back on an unhandled error."""
    db = sessionmaker()
    try:
        yield db
    except BaseException:
        db.rollback()
        raise
    finally:
        db.close()


def _decimal_or_fail(value: str, field: str) -> Decimal:
    try:
        return Decimal(value)
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise _ToolError(
            "INVALID_ARGUMENTS", f'{field} must be a decimal string such as "1500.00"'
        ) from exc


def _variant_row(variant: Any, stock: Any) -> dict[str, Any]:
    return {
        "sku": variant.sku,
        "product": variant.product_name,
        "variant": variant.name,
        "slug": variant.product_slug,
        "category": variant.category_slug,
        "price": str(variant.price),
        "currency": variant.currency,
        "stock_status": None if stock is None else stock.status.value,
        "attributes": dict(variant.attributes),
        "tags": list(variant.tags),
    }


def _ranked_row(candidate: Any) -> dict[str, Any]:
    """A ranked candidate with the reason and score the engine assigned it.

    `reason` is the ranking engine's own label — a model may paraphrase it but
    never author it, because it is a claim about a computation the model did not
    perform (ADR-004, ADR-010).
    """
    variant = candidate.variant
    stock = getattr(candidate, "stock_status", None)
    return {
        "sku": variant.sku,
        "product": variant.product_name,
        "variant": variant.name,
        "slug": variant.product_slug,
        "category": variant.category_slug,
        "price": str(variant.price),
        "currency": variant.currency,
        "stock_status": stock.value if hasattr(stock, "value") else stock,
        "attributes": dict(variant.attributes),
        "rank": candidate.rank,
        "reason": candidate.explanation.text,
        "score": str(candidate.score.final_score),
        "ranking_profile": candidate.score.profile_name,
    }


def _razorpay_client(settings: Any) -> RazorpayClient:
    from app.payments.sdk import build_api

    secret = (
        None
        if settings.razorpay_key_secret is None
        else settings.razorpay_key_secret.get_secret_value()
    )
    return RazorpayClient(
        build_api(settings.razorpay_key_id, secret),
        key_id=settings.razorpay_key_id or "",
        merchant_name=settings.default_merchant_name,
    )


def _frontend_url(settings: Any) -> str:
    origins = settings.cors_allowed_origins
    return origins[0].rstrip("/") if origins else "http://127.0.0.1:5173"
