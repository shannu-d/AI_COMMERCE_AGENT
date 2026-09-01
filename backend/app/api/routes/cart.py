"""Cart endpoints (M7; F§26, F§12, F§13, ADR-010).

The four F§26 names, and no more: `GET /api/cart`, `POST /api/cart/items`,
`PATCH /api/cart/items/{id}`, `DELETE /api/cart/items/{id}`. F§26 says not to
create duplicate APIs where equivalent services exist, so there is no
"recalculate" route and no "set totals" route — recalculation is what every one
of these already does, and totals are never set by anyone.

**Client-supplied amounts are ignored, and the way they are ignored is that
there is nowhere to put one.** The request models are `extra="forbid"` and
declare only a variant and a quantity, so a client sending `unit_price` gets a
422 rather than a silently-dropped field. F§12 requires the frontend never to sum
line items; this is the half of that contract the backend owns.

`POST /api/cart/approve` is deliberately **not here**. Approval is M8, it is the
only path that may write an `APPROVED` row, and it mints the idempotency key
(ADR-007, ADR-013). It gets its own module when its decisions are implemented.
"""

from __future__ import annotations

import uuid
from decimal import Decimal, InvalidOperation

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session as DbSession

from app.agent.errors import ApiErrorCode
from app.api.schemas.cart import (
    AddItemRequest,
    ApprovalResponse,
    ApproveCartRequest,
    CartResponse,
    UpdateItemRequest,
)
from app.config import Settings, get_settings
from app.db.session import get_db
from app.domain.approval import ApprovalFailure
from app.domain.conversation import ConversationState
from app.services.approval_service import ApprovalError, ApprovalService
from app.services.cart_service import CartError, CartService
from app.services.session_service import SessionService

router = APIRouter(tags=["cart"])


def _require_session(db: DbSession, merchant_id: uuid.UUID, session_id: uuid.UUID) -> uuid.UUID:
    """The session, or a 404.

    Same rule as `/api/chat` (ADR-010): an unknown session is rejected rather
    than silently created, so a typo cannot strand a buyer in a cart they will
    never see again.
    """
    if SessionService(db).get(merchant_id, session_id) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": ApiErrorCode.VALIDATION_ERROR.value,
                "message": "SESSION_NOT_FOUND: no such session for this merchant",
            },
        )
    return session_id


def _handle(error: CartError) -> HTTPException:
    """A `CartError` as an HTTP failure.

    `4xx` here, unlike in `/api/chat`, and the difference is deliberate. A chat
    turn that ends in a business failure is a *successful conversational turn*
    carrying an `error` body, because the frontend renders it as part of the
    conversation. A direct REST call that names a variant which does not exist
    is a malformed request, and a client should see it in its error path.
    """
    codes = {
        ApiErrorCode.VARIANT_NOT_FOUND.value: status.HTTP_404_NOT_FOUND,
        ApiErrorCode.OUT_OF_STOCK.value: status.HTTP_409_CONFLICT,
    }
    return HTTPException(
        status_code=codes.get(error.code, status.HTTP_422_UNPROCESSABLE_CONTENT),
        detail={"code": error.code, "message": error.message, "details": error.details},
    )


def _handle_approval(error: Exception) -> HTTPException:
    """An approval failure as an HTTP status.

    A stale version or a changed total is a **409**: the request was well-formed
    and the world moved underneath it. The frontend renders that as "the cart
    changed, please review it again" - a recovery flow, not a bug report - which
    is the same reasoning ADR-010 applies to keeping business outcomes out of the
    client's network-error path.
    """
    if isinstance(error, InvalidOperation):
        return HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={
                "code": ApiErrorCode.VALIDATION_ERROR.value,
                "message": "expected_total is not a valid amount",
            },
        )
    conflicts = {
        ApprovalFailure.CART_VERSION_STALE,
        ApprovalFailure.TOTAL_CHANGED,
        ApprovalFailure.ITEMS_CHANGED,
    }
    code = (
        status.HTTP_409_CONFLICT
        if error.failure in conflicts
        else status.HTTP_422_UNPROCESSABLE_CONTENT
    )
    return HTTPException(
        status_code=code,
        detail={
            "code": error.failure.value,
            "message": error.message,
            "details": error.details,
        },
    )


@router.get(
    "/cart",
    response_model=CartResponse,
    summary="The session's current cart, priced from the catalog as it is now",
)
def get_cart(
    session_id: uuid.UUID,
    db: DbSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> CartResponse:
    """Read the cart. Creates nothing — an empty response means no cart yet."""
    merchant_id = settings.default_merchant_id
    _require_session(db, merchant_id, session_id)

    cart = CartService(db).get_active(merchant_id, session_id)
    if cart is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": ApiErrorCode.VALIDATION_ERROR.value,
                "message": "this session has no active cart",
            },
        )
    return CartResponse.of(cart)


@router.post(
    "/cart/items",
    response_model=CartResponse,
    status_code=status.HTTP_200_OK,
    summary="Add a variant to the cart, or increase the quantity of its line",
)
def add_item(
    request: AddItemRequest,
    db: DbSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> CartResponse:
    merchant_id = settings.default_merchant_id
    session_id = _require_session(db, merchant_id, request.session_id)
    try:
        cart = CartService(db).add_item(
            merchant_id, session_id, request.variant_id, request.quantity
        )
    except CartError as error:
        db.rollback()
        raise _handle(error) from error
    db.commit()
    return CartResponse.of(cart)


@router.patch(
    "/cart/items/{item_id}",
    response_model=CartResponse,
    summary="Set a line's quantity. Zero removes the line.",
)
def update_item(
    item_id: uuid.UUID,
    request: UpdateItemRequest,
    db: DbSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> CartResponse:
    merchant_id = settings.default_merchant_id
    session_id = _require_session(db, merchant_id, request.session_id)
    try:
        cart = CartService(db).set_quantity(merchant_id, session_id, item_id, request.quantity)
    except CartError as error:
        db.rollback()
        raise _handle(error) from error
    db.commit()
    return CartResponse.of(cart)


@router.delete(
    "/cart/items/{item_id}",
    response_model=CartResponse,
    summary="Remove a line",
)
def remove_item(
    item_id: uuid.UUID,
    session_id: uuid.UUID,
    db: DbSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> CartResponse:
    merchant_id = settings.default_merchant_id
    _require_session(db, merchant_id, session_id)
    try:
        cart = CartService(db).remove_item(merchant_id, session_id, item_id)
    except CartError as error:
        db.rollback()
        raise _handle(error) from error
    db.commit()
    return CartResponse.of(cart)


@router.post(
    "/cart/approve",
    response_model=ApprovalResponse,
    status_code=status.HTTP_200_OK,
    summary="The buyer authorizes one exact cart version and total",
    responses={
        404: {"description": "Unknown session, or no active cart."},
        409: {"description": "The cart changed since the buyer saw it (CART_VERSION_STALE)."},
    },
)
def approve_cart(
    request: ApproveCartRequest,
    db: DbSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> ApprovalResponse:
    """**The only path in the system that writes an APPROVED approval** (ADR-007).

    It exists so that the authorization signal originates from a buyer's
    deliberate action rather than from a model's judgement about what "yeah,
    sure" meant. `request_approval()` can ask; only this can answer.

    A stale `cart_version` is a `409`, not a `422`: the request was well-formed
    and the world moved. The frontend renders that as "the cart changed, please
    review it again", which is a recovery flow rather than a bug report.
    """
    merchant_id = settings.default_merchant_id
    session_id = _require_session(db, merchant_id, request.session_id)

    carts = CartService(db)
    cart = carts.get_active(merchant_id, session_id)
    if cart is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": ApiErrorCode.VALIDATION_ERROR.value,
                "message": "this session has no active cart",
            },
        )

    # Re-priced first, deliberately. If the catalog moved since the buyer's
    # screen was drawn, this bumps the version and supersedes any earlier
    # approval - so the version check below then fails, and the buyer is asked
    # to look again rather than authorizing a total that is no longer real
    # (ADR-007, ADR-014, A§28).
    cart = carts.refresh(merchant_id, cart.id)

    approvals = ApprovalService(db, ttl_seconds=settings.approval_ttl_seconds)
    try:
        approval = approvals.approve(
            session_id,
            cart,
            cart_version=request.cart_version,
            expected_total=(
                None if request.expected_total is None else Decimal(request.expected_total)
            ),
        )
    except InvalidOperation as error:
        # A malformed `expected_total`. Nothing was legitimately done, so the
        # re-pricing above is discarded with it.
        db.rollback()
        raise _handle_approval(error) from error
    except ApprovalError as error:
        # **Committed, not rolled back**, and this is the difference between a
        # recovery flow and a dead end.
        #
        # The refresh above is legitimate work: the catalog really did move, the
        # cart really is at a new version, and its old approvals really were
        # superseded. Rolling that back would put the cart straight back to the
        # stale state, so the buyer's next attempt would re-price, bump, fail and
        # roll back again - forever. An integration test walking the price-drift
        # recovery found exactly that.
        #
        # Committing means the 409 below reports a `current_version` the buyer
        # can actually approve, which is what ADR-014's recovery requires.
        db.commit()
        raise _handle_approval(error) from error

    SessionService(db).set_state(merchant_id, session_id, ConversationState.APPROVED)
    db.commit()

    return ApprovalResponse(
        approval_id=approval.id,
        status=approval.status.value,
        cart_version=approval.cart_version,
        approved_total=str(approval.approved_total.quantize(Decimal("0.01"))),
        currency=approval.currency,
        approved_at=approval.approved_at.isoformat() if approval.approved_at else None,
        expires_at=approval.expires_at.isoformat(),
        idempotency_key=approvals.idempotency_key_for(cart.id, approval.cart_version),
        cart=CartResponse.of(cart),
    )
