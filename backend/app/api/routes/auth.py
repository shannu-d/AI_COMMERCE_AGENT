"""`/api/auth/*` — registration, login, logout, and "who am I" (ADR-023).

Four endpoints and no more. Everything security-bearing is in
`AuthService`; this module maps its outcomes onto status codes and shapes.

**There is no `role` field anywhere in a request.** Self-service registration
creates a CUSTOMER, full stop — a merchant administrator is provisioned by an
operator through `AuthService.create_merchant_user`, which no route reaches. So
privilege cannot be granted by a request body, which is the one thing a
registration endpoint most often gets wrong.

**Login claims the caller's anonymous session** (`session_id` in the body, the
same identifier the cart routes already take). The cart hangs off the session,
so it simply gains an owner — no merge, no data movement. A session already
owned by somebody else is left alone.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session as DbSession

from app.agent.errors import ApiErrorCode
from app.api.deps import CurrentUser, MaybeUser, bearer_token
from app.db.session import get_db
from app.domain.identity import AuthenticatedUser
from app.services.auth_service import MIN_PASSWORD_LENGTH, AuthError, AuthService

router = APIRouter(prefix="/auth", tags=["auth"])


class _Request(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class RegisterRequest(_Request):
    email: str = Field(max_length=320)
    password: str = Field(min_length=MIN_PASSWORD_LENGTH, max_length=1024)
    display_name: str | None = Field(default=None, max_length=120)
    #: The anonymous session to claim, so a cart built before signing up
    #: survives. Optional — a shopper may register before ever holding one.
    session_id: uuid.UUID | None = None


class LoginRequest(_Request):
    email: str = Field(max_length=320)
    password: str = Field(max_length=1024)
    session_id: uuid.UUID | None = None


class UserResponse(BaseModel):
    """The principal, as a client may see it. No hash, no token, no internals."""

    id: uuid.UUID
    email: str
    role: str
    display_name: str | None = None
    #: Present only for a merchant administrator. A customer's is always null.
    merchant_id: uuid.UUID | None = None

    @classmethod
    def of(cls, user: AuthenticatedUser) -> UserResponse:
        return cls(
            id=user.id,
            email=user.email,
            role=user.role.value,
            display_name=user.display_name,
            merchant_id=user.merchant_id,
        )


class TokenResponse(BaseModel):
    """The one and only time a token's raw value exists outside the client."""

    access_token: str
    token_type: str = "bearer"
    expires_at: str
    user: UserResponse
    #: Whether the anonymous session sent with the request now belongs to this
    #: user. `false` means the client should start a fresh one — its cart was
    #: already owned by somebody else.
    session_claimed: bool = False


def _fail(error: AuthError) -> HTTPException:
    codes = {
        "VALIDATION_ERROR": 422,
        "INVALID_CREDENTIALS": status.HTTP_401_UNAUTHORIZED,
    }
    return HTTPException(
        status_code=codes.get(error.code, status.HTTP_400_BAD_REQUEST),
        detail={
            "code": ApiErrorCode.VALIDATION_ERROR.value,
            "message": error.message,
            "details": {},
        },
        headers={"WWW-Authenticate": "Bearer"} if error.code == "INVALID_CREDENTIALS" else None,
    )


@router.post(
    "/register",
    response_model=TokenResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a customer account and sign in",
)
def register(
    body: RegisterRequest,
    db: Annotated[DbSession, Depends(get_db)],
) -> TokenResponse:
    """Register a **customer**. There is no way to ask for another role here."""
    service = AuthService(db)
    try:
        service.register_customer(
            email=body.email, password=body.password, display_name=body.display_name
        )
        issued = service.login(email=body.email, password=body.password)
        claimed = service.claim_session(issued.user.id, body.session_id)
    except AuthError as error:
        db.rollback()
        raise _fail(error) from error
    db.commit()
    return TokenResponse(
        access_token=issued.token,
        expires_at=issued.expires_at.isoformat(),
        user=UserResponse.of(issued.user),
        session_claimed=claimed,
    )


@router.post("/login", response_model=TokenResponse, summary="Sign in")
def login(
    body: LoginRequest,
    db: Annotated[DbSession, Depends(get_db)],
) -> TokenResponse:
    service = AuthService(db)
    try:
        issued = service.login(email=body.email, password=body.password)
        claimed = service.claim_session(issued.user.id, body.session_id)
    except AuthError as error:
        db.rollback()
        raise _fail(error) from error
    db.commit()
    return TokenResponse(
        access_token=issued.token,
        expires_at=issued.expires_at.isoformat(),
        user=UserResponse.of(issued.user),
        session_claimed=claimed,
    )


@router.post(
    "/logout",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Revoke the presented token",
)
def logout(
    token: Annotated[str | None, Depends(bearer_token)],
    db: Annotated[DbSession, Depends(get_db)],
) -> None:
    """Idempotent, and deliberately answers 204 even for an unknown token —
    "log me out" should never fail, and a distinct error would report whether a
    token was real."""
    if token:
        AuthService(db).logout(token)
        db.commit()


@router.get("/me", response_model=UserResponse, summary="The signed-in user")
def me(user: CurrentUser) -> UserResponse:
    """Any authenticated principal, customer or merchant.

    `CurrentUser` is `require_customer`, so a merchant reads themselves through
    the same route only if they are also a customer — which they are not. The
    merchant dashboard has its own `/api/merchant/me`.
    """
    return UserResponse.of(user)


@router.get(
    "/session",
    response_model=UserResponse | None,
    summary="The signed-in user, or null — never 401",
)
def current_session(user: MaybeUser) -> UserResponse | None:
    """What the frontend calls on boot to decide whether to show a login link.

    Returns `null` for an anonymous caller rather than 401, so the normal
    logged-out case is not an error in the browser console and does not trip the
    client's error handling.
    """
    return None if user is None else UserResponse.of(user)
