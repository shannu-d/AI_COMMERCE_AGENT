"""Configuration behaviour.

The rules under test here are safety rules, not conveniences: a SQLite URL must
be impossible to configure (ADR-002), secrets must not print themselves
(architecture.md L§45), and the merchant identifier must be a fixed, derivable
value rather than something discovered at runtime (ADR-002).
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.config import Settings
from app.identifiers import DEFAULT_MERCHANT_ID, seed_id


def test_defaults_are_usable_without_any_environment() -> None:
    settings = Settings(_env_file=None)  # type: ignore[call-arg]

    assert settings.environment == "test"  # conftest sets this
    assert settings.database_url.startswith("postgresql")
    assert settings.max_tool_calls_per_turn == 8  # ADR-009
    assert settings.approval_ttl_seconds == 900  # ADR-007
    assert settings.idempotency_ttl_seconds == 86_400  # ADR-013
    assert settings.spending_limit == Decimal("10000.00")  # ADR-011
    assert settings.agent_trace_enabled is False  # ADR-010


@pytest.mark.parametrize(
    "url",
    [
        "sqlite:///./local.db",
        "sqlite+aiosqlite:///./local.db",
        "mysql://user:pass@localhost/db",
        "postgres://user:pass@localhost/db",  # the deprecated scheme psycopg rejects
    ],
)
def test_non_postgres_database_url_is_rejected(url: str) -> None:
    """ADR-002: PostgreSQL only, in every environment including tests."""
    with pytest.raises(ValidationError) as exc_info:
        Settings(_env_file=None, database_url=url)  # type: ignore[call-arg]

    assert "ADR-002" in str(exc_info.value)


def test_postgres_urls_are_accepted() -> None:
    for url in (
        "postgresql://u:p@localhost:5432/db",
        "postgresql+psycopg://u:p@localhost:5432/db",
    ):
        assert Settings(_env_file=None, database_url=url).database_url == url  # type: ignore[call-arg]


def test_secrets_do_not_appear_in_repr_or_str() -> None:
    """architecture.md L§45: secrets never leak through incidental output."""
    settings = Settings(  # type: ignore[call-arg]
        _env_file=None,
        groq_api_key="gsk-super-secret-value",
        razorpay_key_secret="rzp-secret-value",
        razorpay_webhook_secret="whsec-secret-value",
    )

    rendered = f"{settings!r} {settings!s}"
    assert "super-secret-value" not in rendered
    assert "rzp-secret-value" not in rendered
    assert "whsec-secret-value" not in rendered

    # ...but the values are retrievable deliberately, for the redaction filter.
    assert settings.secret_values() == [
        "gsk-super-secret-value",
        "rzp-secret-value",
        "whsec-secret-value",
    ]


def test_secret_values_is_empty_when_nothing_is_configured() -> None:
    assert Settings(_env_file=None).secret_values() == []  # type: ignore[call-arg]


def test_spending_limit_must_be_positive() -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, spending_limit=Decimal("0"))  # type: ignore[call-arg]


def test_currency_must_be_three_letters_and_is_upcased() -> None:
    assert Settings(_env_file=None, spending_limit_currency="inr").spending_limit_currency == "INR"  # type: ignore[call-arg]

    with pytest.raises(ValidationError):
        Settings(_env_file=None, spending_limit_currency="RUPEES")  # type: ignore[call-arg]


def test_default_merchant_id_is_deterministic() -> None:
    """ADR-002: merchant scoping is configured, not discovered."""
    settings = Settings(_env_file=None)  # type: ignore[call-arg]

    assert settings.default_merchant_id == DEFAULT_MERCHANT_ID
    assert settings.default_merchant_id == seed_id("merchant", "circuitcraft")
    assert isinstance(settings.default_merchant_id, uuid.UUID)


def test_seed_id_is_stable_and_case_insensitive() -> None:
    assert seed_id("product", "aerocase-pro") == seed_id("PRODUCT", "AeroCase-Pro")
    assert seed_id("product", "aerocase-pro") != seed_id("product", "shieldcase-premium")
    assert seed_id("product", "x") != seed_id("variant", "x")
