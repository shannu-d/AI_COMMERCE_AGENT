"""Cross-origin access for the frontend (M14, F1).

Without CORS no browser can call this API from any origin but its own, which
makes every frontend of every scope impossible. These tests assert the
behaviour a browser actually depends on - the preflight answer and the
`Access-Control-Allow-Origin` echo - rather than asserting that a middleware
object is installed, because the installed-but-misconfigured case is the one
that costs a day to find.

ADR-017 records why the origin list is explicit and why credentials are off.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.config import Settings, get_settings
from app.main import create_app

ALLOWED = "http://localhost:5173"
FOREIGN = "http://evil.example"


@pytest.fixture
def cors_client() -> TestClient:
    """A client whose app was built with the default origin list."""
    get_settings.cache_clear()
    try:
        yield TestClient(create_app())
    finally:
        get_settings.cache_clear()


# -- The preflight, which is what actually gates a real request --------------


def test_preflight_from_an_allowed_origin_is_approved(cors_client: TestClient) -> None:
    response = cors_client.options(
        "/api/chat",
        headers={
            "Origin": ALLOWED,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == ALLOWED
    assert "POST" in response.headers["access-control-allow-methods"]


def test_preflight_from_an_unlisted_origin_is_not_approved(cors_client: TestClient) -> None:
    """The refusal a wildcard would have removed."""
    response = cors_client.options(
        "/api/chat",
        headers={
            "Origin": FOREIGN,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        },
    )

    # Starlette answers the preflight, but without the header that would let the
    # browser proceed. The absence is the whole control.
    assert "access-control-allow-origin" not in response.headers


def test_a_simple_request_echoes_the_allowed_origin(cors_client: TestClient) -> None:
    response = cors_client.get("/api/health", headers={"Origin": ALLOWED})

    assert response.status_code in (200, 503)
    assert response.headers["access-control-allow-origin"] == ALLOWED


def test_an_unlisted_origin_gets_no_allow_header_on_a_real_response(
    cors_client: TestClient,
) -> None:
    """The response still arrives; the browser is what refuses to hand it over."""
    response = cors_client.get("/api/health", headers={"Origin": FOREIGN})

    assert "access-control-allow-origin" not in response.headers


def test_credentials_are_never_allowed(cors_client: TestClient) -> None:
    """ADR-017: nothing reads a cookie or Authorization header, so no page may
    borrow ambient authority across origins."""
    response = cors_client.get("/api/health", headers={"Origin": ALLOWED})

    assert "access-control-allow-credentials" not in response.headers


def test_every_method_the_api_actually_uses_is_permitted(cors_client: TestClient) -> None:
    """DELETE and PATCH are real routes on /api/cart; a default method list
    would have silently omitted them."""
    for method in ("GET", "POST", "PATCH", "DELETE"):
        response = cors_client.options(
            "/api/cart/items/whatever",
            headers={
                "Origin": ALLOWED,
                "Access-Control-Request-Method": method,
            },
        )
        assert method in response.headers.get("access-control-allow-methods", ""), method


# -- Configuration ------------------------------------------------------------


def test_wildcard_origin_is_rejected() -> None:
    with pytest.raises(ValidationError) as exc_info:
        Settings(_env_file=None, cors_allowed_origins=["*"])  # type: ignore[call-arg]

    assert "ADR-017" in str(exc_info.value)


@pytest.mark.parametrize(
    "origin",
    [
        "localhost:5173",  # no scheme
        "http://localhost:5173/",  # trailing slash - matches nothing
        "http://localhost:5173/app",  # a path - matches nothing
        "ftp://localhost:5173",
    ],
)
def test_an_origin_a_browser_could_never_send_is_rejected(origin: str) -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, cors_allowed_origins=[origin])  # type: ignore[call-arg]


def test_a_comma_separated_string_is_accepted() -> None:
    """So `.env` stays uniform instead of needing JSON for this one value."""
    settings = Settings(  # type: ignore[call-arg]
        _env_file=None,
        cors_allowed_origins="http://localhost:5173, https://shop.example",
    )

    assert settings.cors_allowed_origins == ["http://localhost:5173", "https://shop.example"]


def test_a_comma_separated_value_survives_the_environment(monkeypatch) -> None:
    """The path that actually broke.

    `Settings(cors_allowed_origins="a,b")` passes a Python string straight to the
    validator and proves nothing about `.env`: pydantic-settings runs `json.loads`
    on a complex type in its environment source *before* any validator runs, so a
    comma-separated list raised `SettingsError` at import time while every
    direct-construction test above still passed. `NoDecode` on the field is what
    turns that off, and this is the only test that would notice if it were removed.
    """
    monkeypatch.setenv("CORS_ALLOWED_ORIGINS", "http://localhost:5173,https://shop.example")

    settings = Settings(_env_file=None)  # type: ignore[call-arg]

    assert settings.cors_allowed_origins == [
        "http://localhost:5173",
        "https://shop.example",
    ]


def test_a_bad_origin_in_the_environment_still_fails_loudly(monkeypatch) -> None:
    """NoDecode must not have disabled validation along with JSON decoding."""
    monkeypatch.setenv("CORS_ALLOWED_ORIGINS", "*")

    with pytest.raises(ValidationError) as exc_info:
        Settings(_env_file=None)  # type: ignore[call-arg]

    assert "ADR-017" in str(exc_info.value)


def test_the_default_is_the_frontend_dev_server() -> None:
    settings = Settings(_env_file=None)  # type: ignore[call-arg]

    assert settings.cors_allowed_origins == [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ]
