# 14 — Security / Reliability Audit

No credential value was read, printed, logged or written to any file during this audit. Where a
secret had to be classified, only its prefix category and length were examined.

## Secret handling

| Control | State | Evidence |
| --- | --- | --- |
| `.env` gitignored | ✅ | `.gitignore:5` |
| `.env` untracked | ✅ | `git ls-files` returns nothing |
| `.env` ever committed | ✅ never | not in history |
| Secrets typed as `SecretStr` | ✅ | `groq_api_key`, `razorpay_key_secret`, `razorpay_webhook_secret` |
| Log redaction filter | ✅ | `Settings.secret_values()` feeds it (A§45) |
| Prompt never carries a secret | ✅ | client refuses a prompt containing a configured secret |
| No secret in frontend source | ✅ | enforced by `test_frontend_contract.py` |
| No `VITE_`-prefixed secret | ✅ | only `VITE_API_BASE_URL` |

**The public/private split is correct.** `razorpay_key_id` is deliberately *not* a `SecretStr` — it is
public by design and reaches the browser at checkout time. The secret and the webhook secret never
leave the server.

**Vite inlines every `VITE_`-prefixed variable into the built bundle**, so a `VITE_GROQ_API_KEY` would
be a published credential readable in DevTools. The project avoids this and a test enforces it.

### Findings

| # | Finding | Severity |
| --- | --- | --- |
| S1 | Until this session, **`GROQ_API_KEY` existed only in a running process's memory**, and four `ANTHROPIC_*` variables held Groq values under wrong names. Corrected and verified. | Was P0, **resolved** |
| S2 | `extra="ignore"` silently discards misspelled variables — no warning that configuration is dead | P2 |
| S3 | `anthropic` SDK installed but undeclared — unnecessary supply-chain surface | P3 |

## Money-moving operations

This is where the design is strongest.

| Threat | Control | Verified |
| --- | --- | --- |
| Model invents a price | No tool accepts a price; every price read from the catalogue | ✅ schema enumeration |
| Model creates an order | `create_order` is not a tool at all; four tests keep it absent | ✅ |
| Model authorizes payment | Only an `approvals` row authorizes; no tool can write one as approved | ✅ |
| Client sets the amount | No endpoint accepts a price | ✅ OpenAPI enumeration |
| Charging an unapproved amount | Policy re-reads price live inside the order transaction | ✅ **live, both directions** |
| Approval reuse after drift | Approval bound to `cart_id + version + total`; drift supersedes | ✅ live |
| Duplicate orders | Application-issued idempotency key; `UniqueConstraint` on the key | ✅ live replay |
| Double provider order | `if order.razorpay_order_id is not None: return` | ✅ code |
| Lost order on provider failure | Internal order committed **before** the provider call | ✅ live — order survived the 503 |
| Spending limit bypass | `_rule_8_spending_limit`, configured not model-supplied | ✅ tests |

**The price-drift guarantee holds live in both directions.** A cheaper price is rejected as firmly as
a dearer one, because the buyer authorized one exact total.

## Webhook security

| Threat | Control | Verified |
| --- | --- | --- |
| Spoofed webhook | HMAC-SHA256 over the **raw** body | ✅ tampered → `400` |
| Timing attack | `hmac.compare_digest` | ✅ code |
| Body-parse before verify | Verification precedes parsing; route binds no Pydantic model | ✅ route signature |
| Replay | `UniqueConstraint("provider","event_id")` | ✅ replay → `ignored` |
| Unverified body reaching the parser | Cannot — order of operations | ✅ |
| Silent failure | Every outcome audited | ✅ 3 event types observed |

**Reliability note (P1):** the process on port 8001 rejected a correctly-signed webhook because
`Settings` is cached with `@lru_cache` at start-up and `.env` had changed since. Not a code defect,
but a real operational trap: **a running process gives no indication it is serving stale
configuration.**

## Injection and input validation

| Vector | Assessment |
| --- | --- |
| SQL injection | **Low risk.** SQLAlchemy parameterised throughout; no string-built SQL found in `app/` |
| Model-driven injection | **Contained.** A model-supplied `variant_id`/`sku` is a lookup key, never a fact. A call to a forbidden tool is reported as *forbidden*, so the attempt is legible in logs. `tests/integration` includes an injection-containment scenario |
| Malformed input | 422 with typed errors across every case tested |
| Oversized money | `_money_from_model` bounds values, so a hallucinated `1e30` fails validation rather than reaching `NUMERIC(12,2)` |
| Error leakage | Internal exception text never reaches the model or the client; `INTERNAL_ERROR` carries a generic sentence (F§25) |

## Trust boundaries

| Boundary | Enforcement |
| --- | --- |
| Model → application | AST guards; no deterministic package imports `app.llm` |
| Provider SDK → application | One import site each (`llm/client.py`, `payments/sdk.py`) |
| Browser → API | Zod at the fetch boundary; CORS configured, not wildcarded |
| Frontend → money | No arithmetic on money anywhere in `src/` |

## Authentication — a stated gap

**There is no authentication.** ADR-006 has no `users` table; a session is an anonymous, server-minted,
unguessable UUID and possession of it is the only capability. Appropriate for this MVP and explicitly
decided — but it means anyone holding a session id controls that cart, and there is no rate limiting
on session creation. **Must be revisited before any real deployment (P1 for production, P3 for the
MVP).**

## Race conditions and isolation

Order creation runs in a transaction that re-reads price and stock live. Idempotency is enforced by a
database constraint rather than a read-then-write check, which is the correct pattern under
concurrency. Cart versioning gives optimistic concurrency: an approval names a version, and a
mutation invalidates it.

Not tested: genuinely concurrent order submission for the same cart. The constraints make the outcome
predictable, but no test forces the race (P2).

## Summary

| Category | Rating |
| --- | --- |
| Secret handling | **Strong** (after this session's fix) |
| Money-path safety | **Very strong** — live-verified |
| Webhook security | **Strong** |
| Input validation | **Strong** |
| Injection resistance | **Strong** |
| Authentication | **Absent by design** — blocks production, not the MVP |
| Configuration reliability | **Weak spot** — silent stale settings, silent dead variables |
