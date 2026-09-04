# 04 — Backend Module Audit

Rating per module: **FULL / PARTIAL / IMPLIED / MISSING / BROKEN**.

## Configuration — `app/config.py` · FULL

Pydantic `Settings`, `env_file=(REPO_ROOT/.env, BACKEND_DIR/.env)`, `extra="ignore"`,
`case_sensitive=False`, cached by `@lru_cache(maxsize=1)`.

Secrets are `SecretStr`. `secret_values()` feeds the logging redaction filter so a secret reaching a
log record by an unforeseen path is still masked (A§45). Startup validators reject a non-PostgreSQL
`DATABASE_URL`, an unknown `RANKING_PROFILE`, a non-positive spending limit, and a placeholder
`GROQ_MODEL` — the last one catches the literal string `"Groq"`, which this audit confirmed was
present in `.env` until it was corrected.

**Finding (P2):** `extra="ignore"` means a misspelled variable is silently discarded. That is what
allowed four dead `ANTHROPIC_*` entries to sit in `.env` looking meaningful.

**Finding (P1):** `groq_api_key` defaults to `None` and `GroqClient.from_settings` then passes
`api_key=""`. A missing key therefore fails per-turn at call time rather than loudly at startup —
the opposite of how `GROQ_MODEL` is treated. See [06-groq-audit](06-groq-audit.md).

## Domain — `app/domain/` (10 files) · FULL

Frozen dataclasses and enums. Three separate state machines (`ConversationState`, approval status,
order status) with distinct owners, never derived from one another (ADR-006/007). `ConversationState`
defines all twenty values up front because widening a `CHECK` costs a migration.

## Repositories — `app/repositories/` (6) · FULL

Thin query layer, merchant-scoped. No business logic. No model import.

## Catalog / Compatibility / Inventory services · FULL

Compatibility implements the ADR-003 pipeline end to end:
`user text → [LLM] phrase → normalize_token() → compatibility_targets → canonical id → rules`.
The model produces only a *phrase*; resolution is deterministic, and unresolvable means ask the
buyer. `ProductRequirement.compatibility_target` is typed as `ResolvedTarget`, so an unresolved
string cannot reach the ranker — the guarantee is structural, not procedural.

**Runtime verified:** "iPhone 16" resolved and produced `EXACT_MATCH` with 3 candidates.

## Ranking — `app/ranking/` (6) · FULL

See [07-ranking-audit](07-ranking-audit.md). Pure: an AST scan found zero imports of SQLAlchemy,
`datetime`, `random`, `time`, `httpx` or the model layer.

## Policy engine — `app/policy/engine.py` · FULL

Ten rules, each a method (`_rule_1_approval` through `_rule_10_idempotency`). It evaluates **all**
rules and returns a de-duplicated list of reason codes rather than stopping at the first failure —
the buyer is told everything that is wrong. Seven reason codes: `APPROVAL_REQUIRED`, `INVALID_CART`,
`INVALID_PRODUCT`, `PRICE_CHANGED`, `OUT_OF_STOCK`, `SPENDING_LIMIT_EXCEEDED`,
`ORDER_ALREADY_EXISTS`.

Pure — it owns no database handle; the caller supplies a context read inside the order transaction.
**Runtime verified:** `POLICY_PASS` audit event recorded on the live order.

## Cart service · FULL

Versioned carts; every mutation increments `cart_version`. Totals are computed server-side from live
catalogue prices, never from client input. `price_changes[]` surfaces drift without mutating stored
state. **Runtime verified:** cart v2, subtotal and total ₹999.00, one line item.

## Approval service · FULL

An approval binds `cart_id + cart_version + approved_total` and carries a 15-minute TTL (observed:
`approved_at` 07:20:52Z, `expires_at` 07:35:52Z). Re-approval supersedes the prior row.
**Runtime verified:** an `APPROVED` row plus a `SUPERSEDED` row, with matching audit events.

## Order service · FULL

The state machine begins at `ORDER_CREATED`. The internal order is committed **before** Razorpay is
called, so a provider failure leaves a visible, retryable, auditable order rather than a lost one.
Idempotency keys are **issued by the application** at approval time; a client-invented key is
rejected with `VALIDATION_ERROR` and the message "that idempotency key was not issued by this
application". **Runtime verified:** `201` with `total_amount_minor: 99900`, and a replay of the same
key returned the identical `order_id`.

## Payments — `app/payments/` · PARTIAL (adapter BLOCKED)

`money.py` converts Decimal to and from integer minor units in one place. `razorpay_client.py` is the
provider boundary and is guarded — `if order.razorpay_order_id is not None: return` prevents double
creation. `sdk.py` imports the SDK lazily inside the constructor, so the application boots without it.

**BROKEN in this environment:** the `razorpay` package is **not installed and not declared** in
`pyproject.toml` — neither in `dependencies` nor in `[project.optional-dependencies].dev`. Live
checkout returns `503 PAYMENT_PENDING`. This is the project's single P0.

## Webhook service · FULL

The verification order is deliberate: signature first, parse second. HMAC-SHA256 over raw bytes,
compared with `hmac.compare_digest`. The route is `async` and takes `Request` — no Pydantic body
model, so the raw bytes survive. Dedupe is `UniqueConstraint("provider", "event_id")`, not a
read-then-write check.

**Runtime verified on a fresh backend:** tampered signature gives `400 rejected`; a valid signature
gives `200 received`; a replay gives `200 ignored`.

## Audit service · FULL

Twelve named event types. **Runtime verified** as a complete ordered trail:
`CART_CREATED` then `USER_APPROVED` then `APPROVAL_SUPERSEDED` then `USER_APPROVED` then
`POLICY_PASS` then `ORDER_CREATED`, alongside `WEBHOOK_SIGNATURE_REJECTED`,
`PAYMENT_WEBHOOK_RECEIVED` and `WEBHOOK_DUPLICATE_IGNORED`.

## LLM layer — `app/llm/` (7) · FULL

`client.py` is the only module importing `groq`. The transport types are provider-agnostic.

Extraction requests **text JSON, not a tool call**, and that is deliberate: tool arguments arrive
from the SDK already JSON-decoded, so a budget of `1500.10` would be a float before the application
saw it, and a `Decimal` built from a lossy float is still lossy. Text output goes through
`loads_decimal` with `parse_float=Decimal`. Malformed output gets exactly one bounded repair and is
never hand-coerced. Truncation, refusal and unexpected tool calls are failures, not empty intents,
and none is retried.

## Agent runtime — `app/agent/` (14) · FULL

The only package deliberately spanning both sides of the boundary. `executor.py` implements A§19
with a load-bearing stage order: the call limit is checked **before** the registry lookup, so a call
that cannot be afforded is never validated, authorized or run. A failed call still consumes one of
the eight, or a model making only bad calls would loop forever. Tool errors are returned, never
raised. Two error vocabularies with exactly one bridge (`to_api_code`); an internal failure never
narrows onto a business code.

`recommendations[]` is built from `TurnMemory` — what the *service* returned — never from the
model's reply.

## API routes — `app/api/` · FULL

Eleven endpoints. See [10-api-audit](10-api-audit.md).

## Missing cases identified

| Gap | Severity |
| --- | --- |
| `razorpay` dependency undeclared and uninstalled | **P0** |
| Missing Groq key fails per-turn rather than at startup | P1 |
| No evaluation harness (M15 / F9) | P2 |
| Order page never driven end to end in a browser | P2 |
| `anthropic` installed but undeclared (orphan package) | P3 |
