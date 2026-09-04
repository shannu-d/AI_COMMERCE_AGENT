"""`/api/account/*` — what a signed-in **customer** may see about themselves.

One endpoint so far: their own orders. It exists because the buyer-facing order
route is addressed by id, and "show me my purchases" is not a question an id can
answer.

**Ownership is derived, never asserted.** The list comes from
`OrderService.list_for_customer`, which joins `orders.session_id` to
`sessions.user_id` — the single ADR-023 rule — so there is no `user_id` on
`orders` that could drift out of step with it, and no request field a caller
could use to ask for somebody else's. The customer comes from the bearer token
and from nowhere else.

A **merchant** administrator gets 403 here rather than an empty list. The
dashboard is not a shopping surface, and answering "you have no orders" would
suggest they might.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session as DbSession

from app.api.deps import CurrentUser
from app.api.schemas.order import OrderResponse
from app.config import Settings, get_settings
from app.db.session import get_db
from app.services.order_service import OrderService

router = APIRouter(prefix="/account", tags=["account"])


class OrderPage(BaseModel):
    """A page of the caller's own orders, newest first."""

    items: list[OrderResponse]
    total: int
    limit: int
    offset: int


@router.get("/orders", response_model=OrderPage, summary="The signed-in customer's orders")
def my_orders(
    user: CurrentUser,
    limit: int = Query(default=25, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: DbSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> OrderPage:
    """Read-only, like every other order read.

    Payment status here comes from `orders.status`, which only a verified
    webhook advances (ADR-012). Nothing on this path can move it.
    """
    service = OrderService(
        db,
        spending_limit=settings.spending_limit,
        spending_limit_currency=settings.spending_limit_currency,
        approval_ttl_seconds=settings.approval_ttl_seconds,
    )
    rows, total = service.list_for_customer(
        settings.default_merchant_id, user.id, limit=limit, offset=offset
    )
    return OrderPage(
        items=[OrderResponse.from_row(row) for row in rows],
        total=total,
        limit=limit,
        offset=offset,
    )
