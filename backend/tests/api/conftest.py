"""Identity fixtures for the API tests (ADR-023).

Every fixture here mints a **real** account through `AuthService` and logs in
through it, rather than fabricating a token row or stubbing a dependency. That
matters: a test double for authentication would let a route pass while the
actual token path was broken, which is the one failure this layer exists to
prevent.

The merchant fixtures use `create_merchant_user`, which no HTTP route reaches —
provisioning an administrator is an operator action, and a test is the closest
thing to one. There is deliberately no fixture that makes a merchant through
`/api/auth/register`, because that path cannot make one and never should.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.db.models import Merchant
from app.db.session import get_db
from app.identifiers import DEFAULT_MERCHANT_ID
from app.main import create_app
from app.services.auth_service import AuthService

#: Long enough to satisfy `MIN_PASSWORD_LENGTH`, and obviously not a real one.
PASSWORD = "correct-horse-battery"


def unique_email(prefix: str) -> str:
    """A fresh address per test — `users.email` is UNIQUE and the outer
    transaction rolls back, but two accounts inside one test must still differ."""
    return f"{prefix}-{uuid.uuid4().hex[:12]}@example.test"


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def app_client(session: Session) -> Iterator[TestClient]:
    """An unauthenticated client bound to the test's rolled-back session."""
    app = create_app()
    app.dependency_overrides[get_db] = lambda: session
    with TestClient(app) as client:
        yield client


# -- customers ---------------------------------------------------------


@pytest.fixture
def customer_token(session: Session) -> str:
    service = AuthService(session)
    email = unique_email("shopper")
    service.register_customer(email=email, password=PASSWORD, display_name="Test Shopper")
    return service.login(email=email, password=PASSWORD).token


@pytest.fixture
def customer_headers(customer_token: str) -> dict[str, str]:
    return _bearer(customer_token)


@pytest.fixture
def other_customer_token(session: Session) -> str:
    """A second, unrelated shopper — for "may A touch B's data?" tests."""
    service = AuthService(session)
    email = unique_email("other-shopper")
    service.register_customer(email=email, password=PASSWORD)
    return service.login(email=email, password=PASSWORD).token


@pytest.fixture
def other_customer_headers(other_customer_token: str) -> dict[str, str]:
    return _bearer(other_customer_token)


# -- merchants ---------------------------------------------------------


@pytest.fixture
def merchant_token(session: Session) -> str:
    """An administrator of the **seeded** merchant."""
    service = AuthService(session)
    email = unique_email("owner")
    service.create_merchant_user(
        email=email,
        password=PASSWORD,
        merchant_id=DEFAULT_MERCHANT_ID,
        display_name="Test Owner",
    )
    return service.login(email=email, password=PASSWORD).token


@pytest.fixture
def merchant_headers(merchant_token: str) -> dict[str, str]:
    return _bearer(merchant_token)


@pytest.fixture
def rival_merchant(session: Session) -> uuid.UUID:
    """A second tenant, with nothing in common with the seeded one."""
    mid = uuid.uuid4()
    session.add(Merchant(id=mid, name=f"Rival {mid.hex[:6]}", currency="INR", is_active=True))
    session.flush()
    return mid


@pytest.fixture
def rival_merchant_headers(session: Session, rival_merchant: uuid.UUID) -> dict[str, str]:
    """An administrator of the *other* tenant — the cross-merchant probe."""
    service = AuthService(session)
    email = unique_email("rival-owner")
    service.create_merchant_user(email=email, password=PASSWORD, merchant_id=rival_merchant)
    return _bearer(service.login(email=email, password=PASSWORD).token)
