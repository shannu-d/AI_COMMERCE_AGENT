"""Typed application configuration.

Every value the application needs at runtime arrives here, from the environment
or from ``.env``, and nowhere else. Secrets are held as ``SecretStr`` so that an
accidental ``repr`` or log line prints ``**********`` rather than the value
(architecture.md L§45, A§45, P§39/RZP-01).

Settings for milestones that are not yet built (Anthropic, Razorpay, policy) are
declared here with safe defaults so that the shape of the configuration surface
is visible and reviewable from the start. Declaring them does not activate
anything: no code outside the milestone that owns a setting reads it.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.identifiers import DEFAULT_MERCHANT_ID

BACKEND_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = BACKEND_DIR.parent


class Settings(BaseSettings):
    """Application settings, validated at construction."""

    model_config = SettingsConfigDict(
        # Repository root first, backend/ second: a backend-local .env wins, so a
        # developer can override one value without copying the whole file.
        env_file=(REPO_ROOT / ".env", BACKEND_DIR / ".env"),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # -- Application ---------------------------------------------------------
    app_name: str = "Merchant AI Commerce Agent"
    environment: Literal["local", "test", "ci", "production"] = "local"
    debug: bool = False
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    log_format: Literal["console", "json"] = "console"

    # -- Database (M1) -------------------------------------------------------
    database_url: str = "postgresql+psycopg://ai_commerce:ai_commerce@localhost:5432/ai_commerce"
    test_database_url: str | None = None
    db_echo: bool = False
    db_pool_size: int = Field(default=5, ge=1, le=50)
    db_connect_timeout_seconds: int = Field(default=5, ge=1, le=60)

    # -- Merchant scoping (ADR-002) -----------------------------------------
    # Resolved server-side and injected into every service call. Never read from
    # model output; never taken from a client request body.
    default_merchant_name: str = "CircuitCraft"
    default_merchant_id: uuid.UUID = DEFAULT_MERCHANT_ID

    # -- Claude (M4) ---------------------------------------------------------
    anthropic_api_key: SecretStr | None = None
    anthropic_model: str = "claude-sonnet-5"
    anthropic_timeout_seconds: int = Field(default=60, ge=1, le=600)
    anthropic_max_retries: int = Field(default=2, ge=0, le=5)

    # -- Agent runtime (M5) --------------------------------------------------
    max_tool_calls_per_turn: int = Field(default=8, ge=1, le=32)  # ADR-009
    agent_trace_enabled: bool = False  # ADR-010

    # -- Policy engine (M9) --------------------------------------------------
    spending_limit: Decimal = Decimal("10000.00")  # ADR-011, per transaction
    spending_limit_currency: str = "INR"
    approval_ttl_seconds: int = Field(default=900, ge=60, le=86_400)  # ADR-007
    idempotency_ttl_seconds: int = Field(default=86_400, ge=3_600)  # ADR-013

    # -- Razorpay (M11/M12) --------------------------------------------------
    # key_id is public and reaches the browser. The other two never leave the
    # backend (ADR-011).
    razorpay_key_id: str | None = None
    razorpay_key_secret: SecretStr | None = None
    razorpay_webhook_secret: SecretStr | None = None

    @field_validator("database_url", "test_database_url")
    @classmethod
    def _must_be_postgres(cls, value: str | None) -> str | None:
        """Reject anything that is not PostgreSQL.

        ADR-002: PostgreSQL is the only supported engine, in every environment
        including tests, because the schema depends on UUID, JSONB and TEXT[].
        A SQLite URL slipping in through configuration would produce a test
        suite that passes against a schema the application never runs on.
        """
        if value is None:
            return None
        if not value.startswith(("postgresql://", "postgresql+psycopg://")):
            raise ValueError(
                "DATABASE_URL must be a PostgreSQL URL "
                "(postgresql:// or postgresql+psycopg://); "
                f"got {value.split(':', 1)[0]!r}. See ADR-002."
            )
        return value

    @field_validator("spending_limit")
    @classmethod
    def _limit_is_positive(cls, value: Decimal) -> Decimal:
        if value <= 0:
            raise ValueError("SPENDING_LIMIT must be greater than zero")
        return value

    @field_validator("spending_limit_currency")
    @classmethod
    def _currency_is_iso_ish(cls, value: str) -> str:
        upper = value.upper()
        if len(upper) != 3 or not upper.isalpha():
            raise ValueError("currency must be a three-letter code, e.g. INR")
        return upper

    # -- Derived -------------------------------------------------------------

    @property
    def is_production(self) -> bool:
        return self.environment == "production"

    def secret_values(self) -> list[str]:
        """Every configured secret, as plain strings.

        Used only by the logging redaction filter, so that a secret which
        reaches a log record through some unforeseen path is still masked
        (architecture.md A§45).
        """
        candidates = (
            self.anthropic_api_key,
            self.razorpay_key_secret,
            self.razorpay_webhook_secret,
        )
        return [s.get_secret_value() for s in candidates if s is not None]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-wide settings, constructed once.

    Cached so that configuration is read and validated exactly once per process.
    Tests that need different values clear the cache via
    ``get_settings.cache_clear()``.
    """
    return Settings()
