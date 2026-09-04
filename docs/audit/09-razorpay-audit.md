# 09 — Razorpay / Webhook Audit

## Headline

**Webhook handling: COMPLETE and RUNTIME VERIFIED.**
**Order creation and payment capture: BLOCKED — and not for the reason the documentation says.**

## The blocker, precisely stated

Live checkout returns:

```
503  {"code": "PAYMENT_PENDING",
      "message": "the razorpay package is not installed; install it to reach the provider"}
```

Confirmed by inspection:

| Check | Result |
| --- | --- |
| `razorpay` importable in `backend/.venv`? | **NOT INSTALLED** |
| Declared in `pyproject.toml` `dependencies`? | **No** |
| Declared in `[project.optional-dependencies].dev`? | **No** |
| Would `pip install -e ".[dev]"` install it? | **No — it appears nowhere** |

So the package is not merely absent from the environment; it is absent from the project's declared
dependency set. A fresh clone followed by the documented install produces the same failure. **This is
the project's only P0.**

### The documentation blames the wrong cause

`app/payments/sdk.py` lines 8–10 assert:

> "This repository has **no Razorpay test key** — `RAZORPAY_KEY_SECRET` is still `REPLACE_ME` — so
> M11's live exit condition is recorded as unperformed rather than faked."

**That is now false.** All three credentials are present, valid and test-mode:

| Setting | State (no values read or printed) |
| --- | --- |
| `RAZORPAY_KEY_ID` | Loads · prefix `rzp_test_` → **TEST MODE** |
| `RAZORPAY_KEY_SECRET` | Loads |
| `RAZORPAY_WEBHOOK_SECRET` | Loads |

`PROGRESS.md` repeats the same stale claim. Anyone reading either document would try to fix the
credentials and get nowhere. The real fix is one dependency declaration.

## Webhook — fully verified at runtime

Tested against a freshly started backend reading the current configuration, using signatures
generated from the real webhook secret (used programmatically, never printed):

| Test | Result |
| --- | --- |
| Tampered signature | **`400` `{"status":"rejected"}`** |
| Valid signature, first delivery | **`200` `{"status":"received"}`** |
| Same event replayed | **`200` `{"status":"ignored"}`** |

An earlier tunnel test through ngrok produced the same three outcomes end to end from the public
internet, and left `WEBHOOK_SIGNATURE_REJECTED`, `PAYMENT_WEBHOOK_RECEIVED` and
`WEBHOOK_DUPLICATE_IGNORED` in the audit table.

### Implementation review

| Requirement | Implementation | Verdict |
| --- | --- | --- |
| Verify against the **raw** body | `raw_body = await request.body()` before any parsing | ✅ |
| Route must not bind a Pydantic body | Signature takes `Request`, `Response`, `DbSession`, `Settings` only | ✅ |
| HMAC-SHA256 | `hmac.new(secret, raw_body, hashlib.sha256).hexdigest()` | ✅ |
| Constant-time comparison | `hmac.compare_digest` | ✅ |
| Verify **before** parsing | "verification first, because an unverified body …" | ✅ |
| Dedupe by constraint, not read-then-write | `UniqueConstraint("provider", "event_id")` | ✅ |
| Audit every outcome | Three distinct event types observed | ✅ |

The ordering matters and is correct: an unverified body is never parsed, so a malformed payload from
an unauthenticated source cannot reach the JSON decoder.

## A caveat discovered during testing

The long-running backend on port **8001** rejected a correctly-signed webhook. The cause is **not a
code defect**: `Settings` is cached with `@lru_cache(maxsize=1)` at process start, and `.env` had
been edited since that process launched, so it was comparing against a stale secret. A freshly
started process on port 8002 verified the identical payload correctly.

**Operational implication:** configuration changes require a restart, and there is no warning when a
running process is serving stale settings. Worth knowing before debugging a signature failure.

## Amount handling

| Concern | Implementation |
| --- | --- |
| Currency | `INR` throughout |
| Minor units | `orders.total_amount_minor` BIGINT, `payments.amount_minor` BIGINT |
| Conversion | Two functions in `app/payments/money.py`, the only site |
| Verified live | `999.00` → `99900` |

## Double-creation guard

`RazorpayClient.create_order` begins with `if order.razorpay_order_id is not None: return`, so an
order that already has a provider id cannot acquire a second one. Unit tested against doubles;
untestable live while the SDK is missing.

## Test doubles

Seventeen payment tests run against a two-method `RazorpayApi` protocol with no credentials and no
HTTP, and the doubles live only under `backend/tests/fixtures/` — never in application code, as the
specification requires.

## Verification levels

| Component | Level |
| --- | --- |
| Webhook signature verification | **RUNTIME VERIFIED** |
| Webhook deduplication | **RUNTIME VERIFIED** |
| Webhook audit events | **RUNTIME VERIFIED** |
| Money conversion | **RUNTIME VERIFIED** |
| Razorpay order creation | 🔴 **BLOCKED** — SDK absent |
| Razorpay Checkout in browser (F6) | 🔴 **BLOCKED** — depends on the above |
| `payment.captured` → order transition | 🔴 **BLOCKED** — needs a real provider order to correlate |
| `payment.failed` → order transition | ⚠️ Integration tested only |

## What unblocks this

Declaring and installing the `razorpay` package. Credentials, tunnel and webhook handling are all
already in place and verified, so the remaining live path should close quickly once the dependency
exists. Exact commands are in [19-final-readiness-report](19-final-readiness-report.md).
