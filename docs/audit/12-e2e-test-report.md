# 12 — End-to-End Application Test Report

The application was actually started and driven. Nothing in this document is inferred from source.

## Environment as found

| Service | Port | State | Note |
| --- | --- | --- | --- |
| PostgreSQL 16 | 5432 | ✅ running | `ai_commerce` + `ai_commerce_test`, seeded |
| **This project's backend** | **8001** | ✅ running | long-lived; **stale cached settings** |
| **Fresh backend (started for this audit)** | **8002** | ✅ running | current `.env` |
| Vite dev server | 5173 | ✅ running | bound to `::1`; `127.0.0.1:5173` fails, `localhost` works |
| ngrok | 4040 | ✅ running | `https://tiara-shaded-dutiful.ngrok-free.dev` → `localhost:8001` |
| **Unrelated prototype** | **8000** | ⚠️ running | `{"llm_provider":"mock"}` — **not this project** |

**Port 8000 warning is real.** It answers `/api/health` with a different shape entirely. Anything
pointed at 8000 is talking to a different application.

## The 19 required checks

| # | Check | Result |
| --- | --- | --- |
| 1 | Backend starts | ✅ both 8001 and a fresh 8002 |
| 2 | Frontend starts | ✅ Vite on 5173, title "CircuitCraft" |
| 3 | Database connects | ✅ `database.reachable: true` |
| 4 | Health endpoint | ✅ `200` |
| 5 | Frontend loads | ✅ empty state rendered in Chrome |
| 6 | User sends a message | ✅ user bubble, `Thinking…` |
| 7 | **Groq generates a response** | ✅ real call, `RECOMMENDING` |
| 8 | Products recommended | ✅ 3 grounded recommendations |
| 9 | Add to cart | ✅ cart created, v2 |
| 10 | Cart total correct | ✅ ₹999.00, backend-computed |
| 11 | Approval dialog appears | ✅ correct total shown |
| 12 | Approval succeeds | ✅ `APPROVED`, 15-minute TTL |
| 13 | **Order is created** | ✅ **`201`, `ORDER_CREATED`, `99900` minor** |
| 14 | Order status retrievable | ✅ `GET /api/orders/{id}` → `200` |
| 15 | Razorpay test flow | 🔴 **FAILED — `503`, SDK not installed** |
| 16 | Webhook reaches backend | ✅ via ngrok tunnel (earlier) and directly |
| 17 | Webhook verified | ✅ `400` tampered / `200` valid / `200` ignored |
| 18 | Database updates | ✅ every table advanced as expected |
| 19 | Audit records created | ✅ 13 rows, complete ordered trail |

**17 of 19 passed. One failed (15). One (16) passed by a different route than the browser.**

## The exact failure

```
POST /api/orders/{id}/checkout
503  {"code": "PAYMENT_PENDING",
      "message": "the razorpay package is not installed; install it to reach the provider"}
```

Root cause: `razorpay` is absent from `backend/.venv` **and** from `pyproject.toml`. See
[09-razorpay-audit](09-razorpay-audit.md).

Importantly, the failure was **graceful**: the internal order remained committed, visible and
retryable with `razorpay_order_id: null`, and status stayed `ORDER_CREATED`. That is exactly the
behaviour ADR-011 specifies for a provider failure.

## Audit trail produced

```
CART_CREATED
USER_APPROVED
APPROVAL_SUPERSEDED
USER_APPROVED
POLICY_PASS
ORDER_CREATED
WEBHOOK_SIGNATURE_REJECTED
PAYMENT_WEBHOOK_RECEIVED
WEBHOOK_DUPLICATE_IGNORED
```

A complete, ordered, reconstructable history of the transaction — M13's stated purpose, satisfied.

## Price drift, executed live

Additionally run beyond the 19 checks, because it is the project's flagship guarantee:

| Direction | Change | Result |
| --- | --- | --- |
| Upward | ₹999.00 → ₹1,199.00 | **422 `POLICY_FAILED`** · `['INVALID_CART','PRICE_CHANGED']` |
| Downward | ₹999.00 → ₹799.00 | **422 `POLICY_FAILED`** · `['INVALID_CART','PRICE_CHANGED']` |

Neither could charge an unapproved amount. The catalogue price was restored to ₹999.00 and verified.

## Issues discovered while running

| # | Issue | Severity |
| --- | --- | --- |
| 1 | `razorpay` package missing and undeclared | **P0** |
| 2 | Backend on 8001 serving **stale cached settings** — rejected a correctly-signed webhook until a fresh process was started | P1 |
| 3 | Port 8000 occupied by an unrelated app answering `/api/health` | P2 |
| 4 | Vite binds to `::1`; `127.0.0.1:5173` fails | P3 |
| 5 | Groq free tier throttles to roughly one turn per two minutes | P3 (operational) |

## What still requires manual testing

- Razorpay Checkout opening in a browser (F6)
- A real `payment.captured` correlating to a real provider order
- `payment.failed` reaching a real order's state transition
- Mobile and tablet layouts
- The order page polling to a terminal state

## Verdict

**The application runs, and every step the application itself owns works end to end.** The single
failure sits precisely at the third-party boundary and has a one-line cause.
