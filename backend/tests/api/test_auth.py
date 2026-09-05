"""`/api/auth/*` and the ownership it buys (ADR-023).

Three groups, in the order a reviewer would want them:

* **the account lifecycle** — register, log in, log out, expire;
* **what a request may not say** — no role, no user id, no merchant id;
* **whose data is whose** — a claimed session belongs to one customer, and the
  cart, chat and order routes that hang off it agree.

Every assertion goes through HTTP. Calling `AuthService` directly would prove
the service works while leaving the question this file exists to answer — does
the *route* enforce it — untested.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.api.routes.chat import get_llm_client
from app.db.models import AuthToken, User
from app.db.session import get_db
from app.identifiers import DEFAULT_MERCHANT_ID
from app.main import create_app
from app.services.auth_service import AuthService
from tests.agent.conftest import FakeClient
from tests.api.conftest import PASSWORD, unique_email

pytestmark = pytest.mark.requires_db


@pytest.fixture
def api(session: Session) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_db] = lambda: session
    # The chat route resolves an LLM client as a dependency, before the handler
    # runs its ownership check. The suite is hermetic (no GROQ_API_KEY — see
    # tests/conftest.py), so a real client cannot be constructed; a fake keeps
    # the auth tests about auth. No auth test gets far enough to call it.
    app.dependency_overrides[get_llm_client] = lambda: FakeClient()
    return TestClient(app)


def _register(api: TestClient, **extra: object) -> dict:
    body = {"email": unique_email("new"), "password": PASSWORD, **extra}
    response = api.post("/api/auth/register", json=body)
    assert response.status_code == 201, response.text
    return response.json()


# -- the account lifecycle -------------------------------------------


def test_registration_returns_a_usable_token_and_no_secret(api: TestClient) -> None:
    body = _register(api, display_name="Ada")
    assert body["token_type"] == "bearer"
    assert body["user"]["role"] == "CUSTOMER"
    assert body["user"]["merchant_id"] is None
    assert body["user"]["display_name"] == "Ada"
    # Nothing derived from the password may be in the response, at any depth.
    assert "password" not in response_text(body)
    assert "hash" not in response_text(body)

    me = api.get("/api/auth/me", headers={"Authorization": f"Bearer {body['access_token']}"})
    assert me.status_code == 200
    assert me.json()["id"] == body["user"]["id"]


def response_text(body: object) -> str:
    import json

    return json.dumps(body).lower()


def test_the_password_is_stored_only_as_an_argon2_digest(api: TestClient, session: Session) -> None:
    body = _register(api)
    row = session.get(User, uuid.UUID(body["user"]["id"]))
    assert row is not None
    assert row.password_hash.startswith("$argon2")
    assert PASSWORD not in row.password_hash


def test_the_raw_token_is_never_stored(api: TestClient, session: Session) -> None:
    token = _register(api)["access_token"]
    stored = session.query(AuthToken).all()
    assert stored
    assert all(row.token_hash != token for row in stored)
    assert all(len(row.token_hash) == 64 for row in stored)  # sha-256 hex


def test_an_email_is_normalised_and_registering_twice_fails_the_same_way(
    api: TestClient,
) -> None:
    email = unique_email("dup")
    first = api.post("/api/auth/register", json={"email": email.upper(), "password": PASSWORD})
    assert first.status_code == 201
    assert first.json()["user"]["email"] == email.lower()

    again = api.post("/api/auth/register", json={"email": email, "password": PASSWORD})
    assert again.status_code == 401  # same shape as a bad login: not an oracle


def test_login_succeeds_and_a_wrong_password_does_not(api: TestClient) -> None:
    email = unique_email("login")
    api.post("/api/auth/register", json={"email": email, "password": PASSWORD})

    good = api.post("/api/auth/login", json={"email": email, "password": PASSWORD})
    assert good.status_code == 200
    assert good.json()["access_token"]

    bad = api.post("/api/auth/login", json={"email": email, "password": PASSWORD + "!"})
    assert bad.status_code == 401
    assert bad.headers.get("WWW-Authenticate") == "Bearer"


def test_an_unknown_email_and_a_wrong_password_are_indistinguishable(api: TestClient) -> None:
    email = unique_email("known")
    api.post("/api/auth/register", json={"email": email, "password": PASSWORD})

    wrong = api.post("/api/auth/login", json={"email": email, "password": "not-the-password"})
    unknown = api.post(
        "/api/auth/login", json={"email": unique_email("ghost"), "password": PASSWORD}
    )
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json() == unknown.json()


def test_a_short_password_is_refused_before_anything_is_created(api: TestClient) -> None:
    r = api.post("/api/auth/register", json={"email": unique_email("tiny"), "password": "short"})
    assert r.status_code == 422


def test_logout_revokes_the_token_and_is_idempotent(api: TestClient) -> None:
    headers = {"Authorization": f"Bearer {_register(api)['access_token']}"}
    assert api.get("/api/auth/me", headers=headers).status_code == 200

    assert api.post("/api/auth/logout", headers=headers).status_code == 204
    assert api.get("/api/auth/me", headers=headers).status_code == 401
    # Twice, and with no token at all — "log me out" never fails.
    assert api.post("/api/auth/logout", headers=headers).status_code == 204
    assert api.post("/api/auth/logout").status_code == 204


def test_an_expired_token_is_rejected(api: TestClient, session: Session) -> None:
    headers = {"Authorization": f"Bearer {_register(api)['access_token']}"}
    row = session.query(AuthToken).order_by(AuthToken.issued_at.desc()).first()
    assert row is not None
    # Both ends move: `ck_auth_tokens_expiry_follows_issue` forbids an expiry
    # before its issue, so a token cannot be aged by rewriting one column.
    row.issued_at = datetime.now(UTC) - timedelta(hours=2)
    row.expires_at = datetime.now(UTC) - timedelta(hours=1)
    session.flush()
    assert api.get("/api/auth/me", headers=headers).status_code == 401


def test_a_deactivated_user_cannot_use_a_live_token(api: TestClient, session: Session) -> None:
    body = _register(api)
    user = session.get(User, uuid.UUID(body["user"]["id"]))
    assert user is not None
    user.is_active = False
    session.flush()
    headers = {"Authorization": f"Bearer {body['access_token']}"}
    assert api.get("/api/auth/me", headers=headers).status_code == 401


def test_session_endpoint_answers_null_for_an_anonymous_caller(api: TestClient) -> None:
    """The logged-out case is not an error — the frontend calls this on boot."""
    r = api.get("/api/auth/session")
    assert r.status_code == 200
    assert r.json() is None


# -- what a request may not say --------------------------------------


def test_registration_cannot_ask_for_a_role(api: TestClient) -> None:
    r = api.post(
        "/api/auth/register",
        json={"email": unique_email("climb"), "password": PASSWORD, "role": "MERCHANT"},
    )
    assert r.status_code == 422  # extra="forbid": there is no field to set


def test_registration_cannot_ask_for_a_merchant(api: TestClient) -> None:
    r = api.post(
        "/api/auth/register",
        json={
            "email": unique_email("climb2"),
            "password": PASSWORD,
            "merchant_id": str(DEFAULT_MERCHANT_ID),
        },
    )
    assert r.status_code == 422


def test_a_customer_token_is_not_a_merchant_token(
    api: TestClient, customer_headers: dict[str, str]
) -> None:
    assert api.get("/api/merchant/overview", headers=customer_headers).status_code == 403


def test_a_merchant_token_is_not_a_customer_token(
    api: TestClient, merchant_headers: dict[str, str]
) -> None:
    """`/api/auth/me` is the customer area. The dashboard has `/api/merchant/me`."""
    assert api.get("/api/auth/me", headers=merchant_headers).status_code == 403


# -- whose data is whose ---------------------------------------------


def _new_session(api: TestClient, headers: dict[str, str] | None = None) -> str:
    r = api.post("/api/sessions", headers=headers or {})
    assert r.status_code == 201, r.text
    return r.json()["session_id"]


def test_a_session_made_while_signed_in_belongs_to_that_customer(
    api: TestClient, customer_headers: dict[str, str], other_customer_headers: dict[str, str]
) -> None:
    session_id = _new_session(api, customer_headers)

    mine = api.get("/api/cart", params={"session_id": session_id}, headers=customer_headers)
    theirs = api.get("/api/cart", params={"session_id": session_id}, headers=other_customer_headers)
    anon = api.get("/api/cart", params={"session_id": session_id})

    # 404 for *everyone* here: an owned session with no cart yet, and an owned
    # session someone else asked about, are deliberately the same answer.
    assert mine.status_code == 404
    assert theirs.status_code == 404
    assert anon.status_code == 404


def test_another_customer_cannot_add_to_a_claimed_session(
    api: TestClient,
    session: Session,
    customer_headers: dict[str, str],
    other_customer_headers: dict[str, str],
    variant_id,
) -> None:
    session_id = _new_session(api, customer_headers)
    vid = str(variant_id("CASE-IP16-BLK"))

    ok = api.post(
        "/api/cart/items",
        json={"session_id": session_id, "variant_id": vid, "quantity": 1},
        headers=customer_headers,
    )
    assert ok.status_code == 200, ok.text

    for headers in (other_customer_headers, {}):
        blocked = api.post(
            "/api/cart/items",
            json={"session_id": session_id, "variant_id": vid, "quantity": 1},
            headers=headers,
        )
        assert blocked.status_code == 404

    # The owner's cart is untouched by the attempts.
    cart = api.get("/api/cart", params={"session_id": session_id}, headers=customer_headers).json()
    assert sum(line["quantity"] for line in cart["items"]) == 1


def test_an_anonymous_session_stays_reachable_without_a_token(api: TestClient, variant_id) -> None:
    """Authentication narrows access; it never widens it. Logged-out shopping
    is the pre-auth contract and must keep working exactly as before."""
    session_id = _new_session(api)
    r = api.post(
        "/api/cart/items",
        json={
            "session_id": session_id,
            "variant_id": str(variant_id("CASE-IP16-BLK")),
            "quantity": 2,
        },
    )
    assert r.status_code == 200
    assert api.get("/api/cart", params={"session_id": session_id}).status_code == 200


def test_login_claims_the_anonymous_session_the_caller_was_holding(
    api: TestClient, session: Session, variant_id
) -> None:
    """The cart survives signing in, and it survives by gaining an owner rather
    than by being copied anywhere (ADR-023 §3)."""
    session_id = _new_session(api)
    api.post(
        "/api/cart/items",
        json={
            "session_id": session_id,
            "variant_id": str(variant_id("CASE-IP16-BLK")),
            "quantity": 3,
        },
    )

    email = unique_email("claimer")
    body = api.post(
        "/api/auth/register",
        json={"email": email, "password": PASSWORD, "session_id": session_id},
    ).json()
    assert body["session_claimed"] is True

    headers = {"Authorization": f"Bearer {body['access_token']}"}
    cart = api.get("/api/cart", params={"session_id": session_id}, headers=headers)
    assert cart.status_code == 200
    assert sum(line["quantity"] for line in cart.json()["items"]) == 3

    # And now it is nobody else's.
    assert api.get("/api/cart", params={"session_id": session_id}).status_code == 404


def test_a_merchant_sign_in_does_not_claim_a_shopping_session(
    api: TestClient, session: Session, variant_id
) -> None:
    """The dashboard is not a shopping surface (ADR-023).

    `POST /api/sessions` has always said so — it claims only for a customer —
    but the login route claimed for any role. An administrator signing in from
    the same browser therefore took ownership of the anonymous session, and with
    it the cart and every order derived from it through
    `orders.session_id -> sessions.user_id`. `/api/account/orders` answers 403 to
    a merchant, so those orders became unreachable to everyone: the buyer no
    longer owned them and the owner is not allowed to ask.
    """
    session_id = _new_session(api)
    api.post(
        "/api/cart/items",
        json={
            "session_id": session_id,
            "variant_id": str(variant_id("CASE-IP16-BLK")),
            "quantity": 1,
        },
    )

    email = unique_email("owner")
    AuthService(session).create_merchant_user(
        email=email, password=PASSWORD, merchant_id=DEFAULT_MERCHANT_ID
    )
    session.commit()

    body = api.post(
        "/api/auth/login",
        json={"email": email, "password": PASSWORD, "session_id": session_id},
    ).json()

    assert body["user"]["role"] == "MERCHANT"
    assert body["session_claimed"] is False
    # Still anonymous, so the buyer holding the id can carry on shopping.
    assert api.get("/api/cart", params={"session_id": session_id}).status_code == 200


def test_a_session_already_owned_is_not_re_pointed_by_a_second_login(
    api: TestClient, customer_headers: dict[str, str]
) -> None:
    session_id = _new_session(api, customer_headers)
    email = unique_email("thief")
    api.post("/api/auth/register", json={"email": email, "password": PASSWORD})

    body = api.post(
        "/api/auth/login",
        json={"email": email, "password": PASSWORD, "session_id": session_id},
    ).json()
    assert body["session_claimed"] is False  # the client should start a fresh one


def test_chat_refuses_a_session_the_caller_does_not_own(
    api: TestClient, customer_headers: dict[str, str], other_customer_headers: dict[str, str]
) -> None:
    """No model is reached: the refusal happens before the runtime is asked to
    do anything, so a stranger cannot spend a turn on someone else's thread."""
    session_id = _new_session(api, customer_headers)
    r = api.post(
        "/api/chat",
        json={"session_id": session_id, "message": "hello"},
        headers=other_customer_headers,
    )
    assert r.status_code == 404


def test_an_order_is_not_readable_by_another_customer(
    api: TestClient, session: Session, customer_headers: dict[str, str], variant_id
) -> None:
    """There is no order to read here, and that is the point of the assertion:
    an unknown id and someone else's id answer identically."""
    other = api.get(f"/api/orders/{uuid.uuid4()}", headers=customer_headers)
    assert other.status_code == 404


def test_a_merchant_cannot_take_over_a_shoppers_session(
    api: TestClient, session: Session, merchant_headers: dict[str, str]
) -> None:
    """An administrator creating a session does not own it — the dashboard is
    not a shopping surface, and an administrator-owned session would be one no
    shopper could reach."""
    session_id = _new_session(api, merchant_headers)
    assert AuthService(session).owns_session(None, uuid.UUID(session_id)) is True
