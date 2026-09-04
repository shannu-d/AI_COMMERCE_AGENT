# 08 — Cart / Approval / Order Audit (the money path)

## What was run

The complete money path was exercised against the live application and the live database during this
audit. Before it, the `orders`, `approvals` and `idempotency_keys` tables were **empty** — the path
had never been executed outside tests. It has now.

## The path, step by step

| # | Step | Endpoint | Result |
| --- | --- | --- | --- |
| 1 | Buyer message | `POST /api/chat` | `200` · `RECOMMENDING` · 3 grounded recommendations |
| 2 | Add to cart | `POST /api/cart/items` | `200` · one line |
| 3 | Read cart | `GET /api/cart` | `200` · `cart_version: 2` · `total: "999.00"` |
| 4 | Authorize | `POST /api/cart/approve` | `200` · `APPROVED` · `approved_total: "999.00"` |
| 5 | Create order | `POST /api/orders` | **`201`** · `ORDER_CREATED` · `total_amount_minor: 99900` |
| 5b | Replay the key | `POST /api/orders` | `201` · **identical `order_id`** |
| 6 | Checkout | `POST /api/orders/{id}/checkout` | 🔴 **`503 PAYMENT_PENDING`** — SDK missing |
| 7 | Read order | `GET /api/orders/{id}` | `200` · `ORDER_CREATED` · `razorpay_order_id: null` |

## Server-side authority — verified

| Guarantee | Evidence |
| --- | --- |
| Price is server-side | The cart response prices every line from the catalogue; no request body carries a price |
| Total is server-side | `subtotal` and `total` computed by `CartService`, never accepted from the client |
| Stock is server-side | `available` and `stock_status` come from `inventory` |
| SKU validated | `variant_id` is a lookup key; an unknown one is rejected |
| Merchant scoped | Every query is merchant-scoped; a foreign variant is removed |
| Minor units correct | `999.00` became `99900` — one conversion site, `app/payments/money.py` |

**No endpoint anywhere accepts a price.** This was checked by enumerating every request schema in the
live OpenAPI document. `POST /api/cart/approve` accepts `expected_total`, which is a *confirmation to
compare against*, not a price to charge — a mismatch fails the approval.

## Idempotency — a stronger design than expected

The application **issues** the idempotency key at approval time and returns it on the approval
response. A client-invented key is refused:

```
400 VALIDATION_ERROR
"that idempotency key was not issued by this application"
```

This is a genuinely good property that no project document states: a client cannot mint its own
order-deduplication namespace. Replaying the issued key returned the identical `order_id` rather than
creating a second order.

## Approval lifecycle — verified

An approval binds `cart_id + cart_version + approved_total` and expires in 15 minutes (observed:
`approved_at` 07:20:52Z, `expires_at` 07:35:52Z). Re-approving supersedes the previous row rather
than leaving two live authorizations. The database showed exactly one `APPROVED` and one
`SUPERSEDED`, and the audit trail recorded `APPROVAL_SUPERSEDED` immediately before the second
`USER_APPROVED`.

## Transaction boundaries

The internal order is committed **before** Razorpay is called (ADR-011). The live order proves it:
it exists with `razorpay_order_id: null` and status `ORDER_CREATED`. A provider failure therefore
leaves a visible, retryable, auditable order rather than a lost one — which is precisely the state
the blocked checkout left behind, and it behaved correctly.

## PRICE DRIFT — the flagship scenario, RUNTIME VERIFIED

This is the most important guarantee in the system, and until this audit it existed only as unit
tests. It was executed live, in both directions, against the real database.

**Method:** build a cart at ₹999.00, approve it at ₹999.00, change the authoritative
`product_variants.price` in PostgreSQL, then attempt order creation.

| Direction | Change | Result | Reason codes |
| --- | --- | --- | --- |
| **Upward** | ₹999.00 → ₹1,199.00 | **HTTP 422 · `POLICY_FAILED`** | `['INVALID_CART', 'PRICE_CHANGED']` |
| **Downward** | ₹999.00 → ₹799.00 | **HTTP 422 · `POLICY_FAILED`** | `['INVALID_CART', 'PRICE_CHANGED']` |

**Neither direction produced an order, and neither could have charged an unapproved amount.**

The downward case is the one that matters most and is easiest to get wrong: a *cheaper* price still
invalidates the approval, because the buyer authorized one exact total and the system will not
substitute a different one — not even a more favourable one — without fresh consent. The
authoritative price was restored to ₹999.00 after the test and re-verified.

The policy engine reports **all** failing rules rather than the first, which is why both
`INVALID_CART` and `PRICE_CHANGED` appear.

## Recovery

`tests/integration/test_scenarios.py::test_price_drift_recovers_through_a_fresh_approval` covers the
path back: drift is surfaced in `price_changes[]`, the buyer re-approves at the new total, and a
fresh idempotency key is issued. Integration tested; not separately driven in a browser.

## Verification levels reached

| Component | Level |
| --- | --- |
| Cart service | **RUNTIME VERIFIED** |
| Approval service | **RUNTIME VERIFIED** |
| Policy engine | **RUNTIME VERIFIED** (`POLICY_PASS` and `POLICY_FAILED` both observed) |
| Order service | **RUNTIME VERIFIED** |
| Idempotency | **RUNTIME VERIFIED** |
| Price drift, both directions | **RUNTIME VERIFIED** |
| Razorpay order creation | 🔴 **BLOCKED** |
| Payment capture | 🔴 **BLOCKED** |

## Verdict

**FULL up to the provider boundary.** Everything the application owns in the money path works and is
now proven at runtime. The only unverified steps are the two that require the Razorpay SDK.
