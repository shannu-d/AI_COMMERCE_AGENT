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
from typing import Annotated, Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

from app.identifiers import DEFAULT_MERCHANT_ID
from app.ranking.weights import DEFAULT_PROFILE_NAME, PROFILE_NAMES

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

    # -- Browser access (M14) ------------------------------------------------
    # The API is called from a separate origin in every realistic setup: the
    # frontend dev server on :5173, this on :8000. Without this list no browser
    # can reach the API at all. Origins are scoped deliberately rather than
    # wildcarded - see the validator below and ADR-017.
    # NoDecode is load-bearing: without it pydantic-settings runs json.loads on
    # the raw environment value before any validator sees it, so a plain
    # comma-separated list raises SettingsError at import time rather than
    # reaching _split_origin_list below.
    cors_allowed_origins: Annotated[list[str], NoDecode] = Field(
        default=["http://localhost:5173", "http://127.0.0.1:5173"]
    )

    # -- Database (M1) -------------------------------------------------------
    database_url: str = "postgresql+psycopg://ai_commerce:ai_commerce@localhost:5432/ai_commerce"
    test_database_url: str | None = None
    db_echo: bool = False
    db_pool_size: int = Field(default=5, ge=1, le=50)
    db_connect_timeout_seconds: int = Field(default=5, ge=1, le=60)

    # -- Catalog read services (M2) -----------------------------------------
    # ADR-009 lists IN_STOCK / LOW_STOCK / OUT_OF_STOCK without fixing the
    # boundary between the first two. It is configuration rather than a literal
    # so the M2 tests do not depend on the production default.
    low_stock_threshold: int = Field(default=5, ge=0, le=1000)

    # -- Ranking engine (M3) -------------------------------------------------
    # R§17 RULE 14: the weights are configurable implementation parameters, not
    # permanent business truths. The profiles themselves are data in
    # `app/ranking/weights.py`; this chooses which one runs by default.
    ranking_profile: str = DEFAULT_PROFILE_NAME
    # RULE 11: "a small number of strong candidates, preferably Top 3".
    ranking_top_k: int = Field(default=3, ge=1, le=20)

    # -- Merchant scoping (ADR-002) -----------------------------------------
    # Resolved server-side and injected into every service call. Never read from
    # model output; never taken from a client request body.
    # Display name only. The identifier below is derived from the original
    # "circuitcraft" natural key and is deliberately unchanged (ADR-021) — the
    # storefront brand is EASY BUY, the merchant row it points at is the same.
    default_merchant_name: str = "EASY BUY"
    default_merchant_id: uuid.UUID = DEFAULT_MERCHANT_ID

    # -- Groq (M4, ADR-018) --------------------------------------------------
    # Groq is the locked provider. The key is read only by app/llm/client.py,
    # which refuses to send a prompt containing any configured secret (L§45).
    # No test needs a key: the model is faked at the LLMClient protocol, never
    # at the network (ADR-015).
    groq_api_key: SecretStr | None = None
    groq_model: str = "openai/gpt-oss-120b"
    groq_timeout_seconds: int = Field(default=60, ge=1, le=600)
    groq_max_retries: int = Field(default=2, ge=0, le=5)

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

    @field_validator("cors_allowed_origins", mode="before")
    @classmethod
    def _split_origin_list(cls, value: object) -> object:
        """Accept a comma-separated string as well as a real list.

        pydantic-settings parses a complex type from the environment as JSON,
        which would make CORS_ALLOWED_ORIGINS the one setting in `.env` that has
        to be written as `["http://..."]`. Splitting on commas keeps the file
        uniform with every other value in it.
        """
        if isinstance(value, str):
            return [part.strip() for part in value.split(",") if part.strip()]
        return value

    @field_validator("cors_allowed_origins")
    @classmethod
    def _origins_are_explicit(cls, value: list[str]) -> list[str]:
        """Reject a wildcard, and reject an origin a browser can never match.

        The wildcard is refused because this API mints and trusts `session_id`
        with no other authentication: a session identifier is the whole of the
        claim "this cart is mine". Allowing every origin would not by itself
        hand a cart over - the identifier is an unguessable UUID and is carried
        in the body rather than a cookie, so nothing is attached ambiently - but
        "no credentials are sent automatically" is a property of today's design,
        not a promise, and `*` would silently outlive it.

        A trailing slash or a path is rejected because the `Origin` header is
        scheme, host and port and nothing else. `http://localhost:5173/` never
        matches any request, and the symptom - every browser call failing, with
        a correct-looking configuration - is expensive to diagnose.
        """
        for origin in value:
            if origin == "*":
                raise ValueError(
                    "CORS_ALLOWED_ORIGINS must not be '*'. List the origins that "
                    "may call this API; session_id is the only thing "
                    "distinguishing one buyer's cart from another's. See ADR-017."
                )
            if not origin.startswith(("http://", "https://")):
                raise ValueError(f"CORS origin {origin!r} must start with http:// or https://")
            if origin.rstrip("/") != origin or origin.count("/") != 2:
                raise ValueError(
                    f"CORS origin {origin!r} must be scheme://host[:port] with no "
                    "trailing slash and no path - a browser's Origin header never "
                    "contains one, so this would match nothing."
                )
        return value

    @field_validator("ranking_profile")
    @classmethod
    def _profile_must_exist(cls, value: str) -> str:
        """Reject an unknown profile name at startup rather than at request time.

        A typo here would otherwise fall back to some default and silently
        change how every product is ordered — the exact failure RULE 8
        (determinism) and RULE 14 (configurability) are meant to prevent.
        """
        if value not in PROFILE_NAMES:
            raise ValueError(
                f"RANKING_PROFILE must be one of {', '.join(PROFILE_NAMES)}; got {value!r}"
            )
        return value

    @field_validator("groq_model")
    @classmethod
    def _model_is_named(cls, value: str) -> str:
        """Reject an empty or placeholder model name at startup.

        The value shipped before ADR-018 was the literal string `Groq`, which is
        not a model identifier and would have failed on the first buyer message
        with a provider 404 rather than at configuration time. Same reasoning as
        `RANKING_PROFILE`: a typo must fail loudly.
        """
        value = value.strip()
        if not value:
            raise ValueError("GROQ_MODEL must name a Groq model, e.g. openai/gpt-oss-120b")
        if value.lower() in {"groq", "default", "model"}:
            raise ValueError(
                f"GROQ_MODEL={value!r} is a placeholder, not a model identifier. "
                "Use a Groq model id such as openai/gpt-oss-120b. See ADR-018."
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
            self.groq_api_key,
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
