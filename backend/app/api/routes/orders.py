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
from app.api.deps import MaybeUser
from app.api.schemas.order import CreateOrderRequest, OrderResponse
from app.config import Settings, get_settings
from app.db.session import get_db
from app.domain.identity import AuthenticatedUser
from app.payments import RazorpayClient, RazorpayError
from app.services.auth_service import AuthService
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


def _guard_session(db: DbSession, user: AuthenticatedUser | None, session_id: uuid.UUID) -> None:
    """Refuse to act on a session this caller does not own (ADR-023 §6).

    Anonymous sessions stay open to whoever holds the id — the pre-auth
    contract. A claimed one is its owner's alone. `404`, never `403`, so the
    money path never confirms that a session or an order exists.
    """
    if not AuthService(db).owns_session(user, session_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": ApiErrorCode.VALIDATION_ERROR.value, "message": "no such order"},
        )


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
    user: MaybeUser,
    db: DbSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> OrderResponse:
    """One order, or a reason there is none.

    A replay of a completed key returns `200` with the stored result rather than
    `201`, because nothing was created — the status code is the honest signal
    that this call did no work (P§15, P§34).

    **A signed-in customer's order lands in their account.** Ownership is derived
    from `orders.session_id` → `sessions.user_id` and never stored on the order,
    so a session still anonymous at this moment produces an order belonging to
    nobody — permanently, because the buyer has already signed in and their next
    login has nothing left to claim. Claiming here closes that window: the buyer
    who signed in and then shopped, or shopped in a second tab that minted its
    own session, still sees what they bought. A session owned by *someone else*
    is not re-pointed — `claim_session` refuses — and a merchant administrator
    never claims one at all.
    """
    if user is not None and user.is_customer:
        AuthService(db).claim_session(user.id, request.session_id)

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

    # ADR-011 step 8: the internal order is committed here, *before* any
    # provider is reached. Everything after this point can fail without losing
    # the record of a purchase the buyer authorized.
    db.commit()

    if not result.replayed:
        _attach_provider_order(db, settings, result.order_id)

    # Re-read so the response carries whatever the provider step achieved,
    # while `replayed` is carried forward from the service - re-reading a row
    # cannot tell whether *this* call created it, and that is exactly the
    # distinction a client retrying after a network timeout needs.
    order = _build(db, settings).get(settings.default_merchant_id, result.order_id)
    return OrderResponse.from_row(order, replayed=result.replayed)


def _attach_provider_order(db: DbSession, settings: Settings, order_id: uuid.UUID) -> None:
    """ADR-011 step 9. A failure here is recorded, not raised.

    The order exists and is committed. If the provider cannot be reached, the
    right outcome is an order in `ORDER_CREATED` with a null `razorpay_order_id`
    - visible, retryable and auditable - not a 500 that suggests to the buyer
    that nothing happened. `POST /api/orders/{id}/checkout` retries it.
    """
    try:
        client = _razorpay(settings)
    except RazorpayError as error:
        logger.warning(
            "no payment provider configured; order left awaiting one",
            extra={"order_id": str(order_id), "reason": str(error)},
        )
        return

    try:
        _build(db, settings).attach_provider_order(settings.default_merchant_id, order_id, client)
        db.commit()
    except (RazorpayError, OrderError):
        db.rollback()
        logger.warning(
            "provider order not created; the internal order stands",
            extra={"order_id": str(order_id)},
        )


def _razorpay(settings: Settings) -> RazorpayClient:
    from app.payments.sdk import build_api

    return RazorpayClient(
        build_api(
            settings.razorpay_key_id,
            None
            if settings.razorpay_key_secret is None
            else settings.razorpay_key_secret.get_secret_value(),
        ),
        key_id=settings.razorpay_key_id or "",
        merchant_name=settings.default_merchant_name,
    )


@router.get(
    "/orders/{order_id}",
    response_model=OrderResponse,
    summary="An order's current state",
)
def get_order(
    order_id: uuid.UUID,
    user: MaybeUser,
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
    _guard_session(db, user, order.session_id)
    return OrderResponse.from_row(order)


@router.post(
    "/orders/{order_id}/checkout",
    summary="Checkout configuration for an order, creating the provider order if needed",
    responses={
        404: {"description": "No such order."},
        503: {"description": "The payment provider could not be reached."},
    },
)
def checkout(
    order_id: uuid.UUID,
    user: MaybeUser,
    db: DbSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict:
    """What the frontend needs to open Razorpay Checkout (P§21, RZP-03).

    Also the retry for ADR-011 step 9: an order left in `ORDER_CREATED` because
    the provider was unreachable gets its provider order here, using the same
    internal order and the same idempotency key - so a network failure cannot
    produce two provider orders.

    The response carries the **public** key id, the amount in minor units, the
    currency and the merchant name. `RAZORPAY_KEY_SECRET` and
    `RAZORPAY_WEBHOOK_SECRET` never appear in it (L§45, RZP-01, RZP-03).

    The frontend's success callback is **not** payment truth (P§28, ADR-012).
    """
    service = _build(db, settings)
    order = service.get(settings.default_merchant_id, order_id)
    if order is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": ApiErrorCode.VALIDATION_ERROR.value, "message": "no such order"},
        )
    _guard_session(db, user, order.session_id)

    try:
        client = _razorpay(settings)
        if order.razorpay_order_id is None:
            order = service.attach_provider_order(settings.default_merchant_id, order_id, client)
            db.commit()
        return dict(client.checkout_config(order))
    except RazorpayError as error:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": ApiErrorCode.PAYMENT_PENDING.value,
                "message": str(error),
            },
        ) from error
