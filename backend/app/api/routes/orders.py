"""`POST /api/orders` and `GET /api/orders/{id}` (M10; ADR-011, ADR-013, F§26).

**The only route in this application that can create an order**, and it is
deliberately small: it validates a request shape, calls one service method, and
maps one exception onto a status code. Every decision worth making happens in
`OrderService`, behind the Policy Engine.

`create_order` is not a tool and never will be (ADR-009, closing D6). There is no
path from a model's output to this route — the agent can propose a cart and ask
for confirmation, and a human presses the button that arrives here.

**Nothing in the request body is authoritative.** It carries a session, a cart, a
claimed `cart_version` and an idempotency key the backend itself minted. It
carries no amount, no price, no item list and no currency. F§17's forged
`amount = ₹1` is not rejected by validation; it has nowhere to be submitted, and
`extra="forbid"` means attempting it is a 422 rather than a field quietly ignored.

**A policy refusal is a 422 with reason codes**, not a 500 and not a silent
failure. The frontend renders each code as its own recovery flow — price drift
sends the buyer back to re-approve, out of stock back to the cart — which is why
the codes are part of the contract rather than log text.
"""

from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session as DbSession

from app.agent.errors import ApiErrorCode
from app.api.schemas.order import CreateOrderRequest, OrderResponse
from app.config import Settings, get_settings
from app.db.session import get_db
from app.services.order_service import OrderError, OrderService

logger = logging.getLogger(__name__)

router = APIRouter(tags=["orders"])

#: How a service refusal reads on the wire. A policy failure is 422 — the request
#: was well-formed and the world said no — while an in-flight duplicate is 409,
#: because it is a genuine conflict with another request rather than a verdict.
_STATUS: dict[str, int] = {
    "POLICY_FAILED": status.HTTP_422_UNPROCESSABLE_CONTENT,
    "ORDER_IN_PROGRESS": status.HTTP_409_CONFLICT,
    "APPROVAL_REQUIRED": status.HTTP_409_CONFLICT,
    "VALIDATION_ERROR": status.HTTP_400_BAD_REQUEST,
    "SERVER_ERROR": status.HTTP_500_INTERNAL_SERVER_ERROR,
}


def _build(db: DbSession, settings: Settings) -> OrderService:
    return OrderService(
        db,
        spending_limit=settings.spending_limit,
        spending_limit_currency=settings.spending_limit_currency,
        approval_ttl_seconds=settings.approval_ttl_seconds,
    )


@router.post(
    "/orders",
    response_model=OrderResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create an order from an approved cart",
    responses={
        409: {"description": "Another request is creating this order, or the approval lapsed."},
        422: {"description": "The Policy Engine refused, with machine-readable reason codes."},
    },
)
def create_order(
    request: CreateOrderRequest,
    db: DbSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> OrderResponse:
    """One order, or a reason there is none.

    A replay of a completed key returns `200` with the stored result rather than
    `201`, because nothing was created — the status code is the honest signal
    that this call did no work (P§15, P§34).
    """
    try:
        result = _build(db, settings).create_order(
            merchant_id=settings.default_merchant_id,
            session_id=request.session_id,
            cart_id=request.cart_id,
            cart_version=request.cart_version,
            idempotency_key=request.idempotency_key,
        )
    except OrderError as error:
        # The service already marked the key FAILED where appropriate; that
        # write must survive, so the transaction is committed rather than rolled
        # back. A key that stayed RESERVED after a refusal would deadlock the
        # buyer's next attempt against a lock nobody holds.
        db.commit()
        raise HTTPException(
            status_code=_STATUS.get(error.code, status.HTTP_400_BAD_REQUEST),
            detail={"code": error.code, "message": error.message, "details": error.details},
        ) from error
    except Exception:
        db.rollback()
        logger.exception("order creation faulted", extra={"cart_id": str(request.cart_id)})
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "code": ApiErrorCode.ORDER_CREATION_FAILED.value,
                "message": "the order could not be created",
            },
        ) from None

    db.commit()
    return OrderResponse.of(result, replayed=result.replayed)


@router.get(
    "/orders/{order_id}",
    response_model=OrderResponse,
    summary="An order's current state",
)
def get_order(
    order_id: uuid.UUID,
    db: DbSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> OrderResponse:
    """Read an order.

    Payment status here comes from `orders.status`, which only a verified webhook
    advances past `RAZORPAY_ORDER_CREATED` (ADR-012). Nothing a buyer or the
    agent says can move it.
    """
    order = _build(db, settings).get(settings.default_merchant_id, order_id)
    if order is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": ApiErrorCode.VALIDATION_ERROR.value,
                "message": "no such order",
            },
        )
    return OrderResponse.from_row(order)
