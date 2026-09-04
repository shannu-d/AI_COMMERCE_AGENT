# 10 — API Audit

Eleven endpoints, enumerated from the **live OpenAPI document**, not from source. Every one was
exercised during this audit.

## Endpoint table

| Method | Path | Purpose | Validation | Auth | DB | Tests | Runtime |
| --- | --- | --- | --- | --- | --- | --- | --- |
| GET | `/api/health` | Liveness and database reachability | none needed | none | ping | ✓ | ✅ `200` |
| POST | `/api/chat` | One buyer message to the agent | Pydantic; message min-length | session id | R/W | ✓ | ✅ `200` live Groq turn |
| GET | `/api/cart` | Current cart, priced from the catalogue | `session_id` UUID required | session id | R | ✓ | ✅ `200` |
| POST | `/api/cart/items` | Add a variant or increase quantity | UUIDs, `quantity >= 1` | session id | R/W | ✓ | ✅ `200` |
| PATCH | `/api/cart/items/{item_id}` | Set a line quantity; zero removes | UUID path, quantity bounds | session id | R/W | ✓ | ⚠️ tests only |
| DELETE | `/api/cart/items/{item_id}` | Remove a line | UUID path | session id | R/W | ✓ | ⚠️ tests only |
| POST | `/api/cart/approve` | Authorize one exact cart version and total | version + `expected_total` must match | session id | R/W | ✓ | ✅ `200 APPROVED` |
| POST | `/api/orders` | Create an order from an approved cart | requires an **application-issued** idempotency key | session id | R/W txn | ✓ | ✅ `201` |
| GET | `/api/orders/{order_id}` | Order state | UUID path | session id | R | ✓ | ✅ `200` |
| POST | `/api/orders/{order_id}/checkout` | Checkout config; creates the provider order | UUID path | session id | R/W | ✓ | 🔴 `503` SDK absent |
| POST | `/api/webhooks/razorpay` | Verified payment events | **HMAC over raw body** | signature | R/W | ✓ | ✅ `400`/`200`/ignored |

**Authentication model:** there is none, by design. ADR-006 has no `users` table. A session is an
anonymous, server-minted, unguessable UUID; possession of it is the only capability. This is
appropriate for the MVP and is the documented decision, not an oversight — but it does mean anyone
holding a session id holds that cart.

## Validation and error responses — tested live

| Case | Expected | Actual |
| --- | --- | --- |
| Missing required query parameter | 422 | **422** `{"type":"missing","loc":["query","session_id"]}` |
| Malformed UUID in query | 422 | **422** `uuid_parsing` |
| Malformed UUID in path | 422 | **422** `uuid_parsing` |
| Unknown session | 404 | **404** `VALIDATION_ERROR: SESSION_NOT_FOUND` |
| Unknown order | 404 | **404** `"no such order"` |
| Empty request body | 422 | **422** `Field required` |
| Empty message string | 422 | **422** `string_too_short` |
| Quantity 0 | 422 | **422** `greater_than_equal` |
| Negative quantity | 422 | **422** `greater_than_equal` |
| Webhook with no signature | 400 | **400** `{"status":"rejected"}` |
| Unknown route | 404 | **404** `Not Found` |
| Client-invented idempotency key | 400 | **400** `"not issued by this application"` |
| Policy failure (price drift) | 422 | **422** `POLICY_FAILED` with reason codes |
| Duplicate order (same key) | same order | **201, identical `order_id`** |

Every case behaved correctly. Two response shapes coexist: FastAPI's own `422` validation envelope
and the application's `{"detail": {"code", "message", "details"}}` business envelope. The frontend
Zod schemas handle both.

## The critical contract property

**No endpoint accepts a price.** Verified by enumerating every request schema in the live OpenAPI
document. `POST /api/cart/approve` accepts `expected_total`, but that is a value to *compare*, not to
charge — a mismatch fails the approval rather than setting the amount.

## Status-code discipline

A business outcome that the turn completed — a policy refusal, an out-of-stock finding — returns
**HTTP 200 with an `error` object**, not a 4xx (ADR-010). Only transport and genuine client errors
produce 4xx/5xx. This is what lets the frontend keep recovery flows out of its error branch, and it
was confirmed live: a Groq rate-limit failure returned `200` with a business error.

## CORS

Verified live: a preflight from `http://localhost:5173` returns
`access-control-allow-origin: http://localhost:5173`. Fifteen CORS tests exist, including one
asserting a foreign origin is refused. Origins are configured, not wildcarded.

## Contract alignment with the frontend

`backend/tests/api/test_frontend_contract.py` fails the build if `API_ERROR_CODES` in
`frontend/src/api/schemas.ts` diverges from `app/agent/errors.py`, and also if a secret-bearing name
appears anywhere in frontend source. The eleven F§25 codes are mirrored by hand and guarded — a rare
and worthwhile piece of cross-language contract enforcement.

## Findings

| # | Finding | Severity |
| --- | --- | --- |
| 1 | `PATCH` and `DELETE` on cart items exercised only by tests, never at runtime | P2 |
| 2 | `/api/orders/{id}/checkout` returns 503 — SDK absent | **P0** |
| 3 | Two error envelope shapes (FastAPI 422 vs business) — handled, but undocumented | P3 |

## Verdict

**FULL**, except the checkout endpoint, which is blocked by the missing dependency rather than by any
defect in the route.
