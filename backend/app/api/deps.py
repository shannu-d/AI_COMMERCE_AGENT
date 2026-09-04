"""Authorization dependencies — the only place a request acquires an identity.

ADR-023 §6. Three dependencies, and nothing else may decide who a caller is:

============================  =================================================
``optional_user``             resolves a bearer token if one is present, `None`
                              otherwise. For routes that must work both ways —
                              browsing, chat, an anonymous cart.
``require_customer``          401 without a valid token, 403 unless CUSTOMER.
``require_merchant``          401 without a valid token, 403 unless MERCHANT,
                              and yields the merchant id from the *user row*.
============================  =================================================

**Nothing here reads identity from the request body, a query parameter, or any
header other than the `Authorization` bearer it verifies.** That is the whole
authorization model: a client can present a token and nothing else, so it can
only ever be whoever that token belongs to.

`require_merchant` returning the merchant id matters more than it looks.
ADR-022's isolation guarantee was "the client cannot name a merchant, because
there is no field for one". This keeps that property and strengthens it: the id
now comes from `users.merchant_id`, so a caller cannot reach *any* merchant
without proving they administer one.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy.orm import Session as DbSession

from app.agent.errors import ApiErrorCode
from app.db.session import get_db
from app.domain.identity import AuthenticatedUser
from app.services.auth_service import AuthService

__all__ = [
    "CurrentMerchant",
    "CurrentUser",
    "MaybeUser",
    "bearer_token",
    "optional_user",
    "require_customer",
    "require_merchant",
]


def _unauthorized(message: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail={"code": ApiErrorCode.VALIDATION_ERROR.value, "message": message, "details": {}},
        # RFC 6750: tell a client *how* to authenticate, not who exists.
        headers={"WWW-Authenticate": "Bearer"},
    )


def _forbidden(message: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail={"code": ApiErrorCode.VALIDATION_ERROR.value, "message": message, "details": {}},
    )


def bearer_token(authorization: Annotated[str | None, Header()] = None) -> str | None:
    """The token from `Authorization: Bearer <token>`, or `None`.

    A malformed header is treated as absent rather than as an error: the caller
    is then anonymous, and a route that requires a user will say so. Answering
    "your header is malformed" would be a slightly more helpful message and a
    slightly more useful probe.
    """
    if not authorization:
        return None
    scheme, _, value = authorization.partition(" ")
    if scheme.lower() != "bearer" or not value.strip():
        return None
    return value.strip()


def optional_user(
    token: Annotated[str | None, Depends(bearer_token)],
    db: Annotated[DbSession, Depends(get_db)],
) -> AuthenticatedUser | None:
    """Whoever is calling, or `None` for an anonymous caller.

    Never raises. An expired, revoked, unknown or malformed token is simply an
    anonymous request — which is a legitimate state everywhere this is used.
    """
    return AuthService(db).authenticate(token)


def require_customer(
    user: Annotated[AuthenticatedUser | None, Depends(optional_user)],
) -> AuthenticatedUser:
    if user is None:
        raise _unauthorized("sign in to continue")
    if not user.is_customer:
        raise _forbidden("this is a customer area")
    return user


def require_merchant(
    user: Annotated[AuthenticatedUser | None, Depends(optional_user)],
) -> AuthenticatedUser:
    if user is None:
        raise _unauthorized("sign in to continue")
    if not user.is_merchant or user.merchant_id is None:
        raise _forbidden("this is a merchant area")
    return user


def require_merchant_id(
    merchant: Annotated[AuthenticatedUser, Depends(require_merchant)],
) -> uuid.UUID:
    """The authenticated merchant's id — the only merchant scope a route may use.

    `require_merchant` has already established `merchant_id is not None`; the
    assert states that for the type checker and would catch a future edit that
    loosened the check above.
    """
    assert merchant.merchant_id is not None
    return merchant.merchant_id


#: Readable aliases for route signatures.
MaybeUser = Annotated[AuthenticatedUser | None, Depends(optional_user)]
CurrentUser = Annotated[AuthenticatedUser, Depends(require_customer)]
CurrentMerchant = Annotated[AuthenticatedUser, Depends(require_merchant)]
