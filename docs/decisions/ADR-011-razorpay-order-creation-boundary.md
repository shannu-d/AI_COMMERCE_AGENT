# ADR-011: The Razorpay Order Creation Boundary

**Status:** Accepted, not implemented (2026-08-30)
**Milestone:** Policy Engine M9; order creation M10; Razorpay M11
**Source references:** `architecture.md` A§15, A§22, A§24, P§1, P§2, P§6, P§7, P§8, P§13, P§14, P§17, P§18, P§19, P§20, P§21, P§31, P§38, P§39, F§15, F§17, F§18
**Related open questions:** C6, D3, D6 (BLOCKING)

## Context

P§19 names this the project's most important security boundary:

> The architecture must NOT be: Claude → Razorpay.
> Correct: Claude → Agent Runtime → Cart → Explicit Approval → Policy Engine → Order Service →
> Razorpay.

P§6 lists the ten checks the Policy Engine performs before order creation. P§7 fixes the output
shape: a decision, machine-readable reason codes, and a validated total. P§17 separates an order
(the application's commerce transaction) from a payment (the money). F§17 adds the adversarial case:
a user who edits frontend JavaScript and posts `amount = ₹1` directly to the API. P§13 requires a
spending limit without saying what it is scoped to.

## Problem

Fix the exact sequence from a buyer's confirmation to a Razorpay order, fix what the Policy Engine
reads and returns, and make it structurally impossible to reach Razorpay by any other route.

## Decision

### The one path to money

```
POST /api/orders  { session_id, cart_id, cart_version, idempotency_key }
  │
  ├─ 1. load session, cart, and the APPROVED approval for (cart_id, cart_version)
  ├─ 2. BEGIN TRANSACTION
  ├─ 3. re-read authoritative prices from product_variants          ← live, not snapshots
  ├─ 4. SELECT ... FOR UPDATE the inventory rows for every line     ← live, and locked
  ├─ 5. PolicyEngine.evaluate(TransactionContext) → PolicyDecision
  ├─ 6. FAIL → rollback, audit POLICY_FAIL, return structured reason codes.  No Razorpay call.
  ├─ 7. PASS → insert orders + order_items, mark the idempotency key COMPLETED
  ├─ 8. COMMIT                                                       ← the internal order now exists
  ├─ 9. call Razorpay, create the test-mode order, store razorpay_order_id
  └─ 10. audit ORDER_CREATED and RAZORPAY_ORDER_CREATED, return checkout configuration
```

**There is no other route.** No tool reaches step 9 (ADR-009: `create_order` is not registered). No
service calls the Razorpay client except `OrderService`. The Razorpay client is constructed only
inside `app/payments/`, and it refuses to build an order from anything but a persisted `Order` row
whose `status` is `ORDER_CREATED`.

### Nothing from the client is authoritative

`POST /api/orders` accepts `session_id`, `cart_id`, `cart_version` and `idempotency_key`. **It does
not accept an amount, a price, an item list or a currency.** Every monetary value is recomputed
server-side from the database. F§17's forged `amount = ₹1` is not rejected by validation; it has
nowhere to be submitted.

`cart_version` is accepted, and it is a *claim to be checked*, not an instruction: if it does not
match the cart's current version the request fails with `CART_VERSION_STALE`.

### The Policy Engine

Deterministic application code. Input `TransactionContext`, output `PolicyDecision`. It has no
network access, no model access, and no side effects — it reads state and returns a verdict, so it
is exhaustively unit-testable.

```python
@dataclass(frozen=True)
class PolicyDecision:
    decision: Literal["PASS", "FAIL"]
    reason_codes: list[str]          # empty iff PASS
    validated_total: Decimal
    currency: str
```

The ten rules of P§6, each independently testable (POLICY-02):

| # | Rule | Reason code on failure |
| --- | --- | --- |
| 1 | An `APPROVED`, unexpired, un-superseded approval exists for this session, cart and version | `APPROVAL_REQUIRED` |
| 2 | The cart is `ACTIVE`, non-empty, and its `items_fingerprint` matches the approval | `INVALID_CART` |
| 3 | Every product is active and belongs to the session's merchant | `INVALID_PRODUCT` |
| 4 | Every variant is active and belongs to its product | `INVALID_PRODUCT` |
| 5 | The live recomputed total equals `approved_total` exactly | `PRICE_CHANGED` |
| 6 | Live available quantity ≥ requested quantity for every line | `OUT_OF_STOCK` |
| 7 | Every quantity is within `1..99` | `INVALID_CART` |
| 8 | The total is within the configured spending limit | `SPENDING_LIMIT_EXCEEDED` |
| 9 | No non-cancelled order already exists for this cart | `ORDER_ALREADY_EXISTS` |
| 10 | The idempotency key is unused, or its stored result is replayable | `ORDER_ALREADY_EXISTS` |

**All rules are evaluated; evaluation does not stop at the first failure.** `reason_codes` is a list
so the buyer is told everything that is wrong in one message rather than discovering problems one
round-trip at a time.

The engine never reads the session's conversation state. `sessions.conversation_state` says
`APPROVED` only because the agent set it; only an `approvals` row is evidence (ADR-007).

### Freshness is not negotiable

Rules 5 and 6 read `product_variants.price` and `inventory` **inside the transaction, at evaluation
time**. They never read `cart_items.unit_price_snapshot`, never read a value cached earlier in the
request, and never read anything the model supplied. RULE 12 and P§11 both require this, and it is
the mechanism that makes the price-drift scenario work (ADR-014).

### The spending limit

Per transaction, from application configuration, one global value, `₹10,000` by default (P§13,
closes D3). Not per session, not per day, not per merchant. P§13 explicitly defers
merchant-configurable policy until the core system is stable. The value is typed configuration, so
the M9 test that a ₹12,000 cart fails does not depend on the production default.

### Concurrency

Policy evaluation and order insertion share one transaction, with `SELECT ... FOR UPDATE` on the
inventory rows (closes C6). Two simultaneous checkouts of the last unit serialize: one passes, the
other fails rule 6. Without the lock both would observe stock and both would create an order.

### Order first, Razorpay second

The internal order is committed **before** Razorpay is called (P§17, P§18). If the Razorpay call
fails, the order exists in `ORDER_CREATED` with a null `razorpay_order_id` — a visible, retryable,
auditable state. The reverse ordering would allow a Razorpay order with no local record, which is
unreconcilable.

Retrying the Razorpay call reuses the same internal order and the same idempotency key, so a network
failure cannot produce two Razorpay orders (ADR-013).

### Checkout handoff

The backend returns the Razorpay order id, the **public** key id, the amount in minor units, the
currency and the merchant display name (P§21, RZP-03). `RAZORPAY_KEY_SECRET` and
`RAZORPAY_WEBHOOK_SECRET` never leave the backend, never appear in a response, never reach the
frontend and never enter a prompt (L§45, RZP-01, RZP-03).

The frontend opens Checkout with that configuration. Its success callback is **not** payment truth
(P§21, P§28, ADR-012).

### Once created, the Razorpay amount is final

A price change after the Razorpay order exists does not retroactively alter it (closes D9). The
Razorpay order fixes the amount at creation, which is the natural boundary of the price-drift
guarantee: the guarantee is that no order is *created* at an unapproved amount.

## Alternatives considered

**Call Razorpay first and persist the order from its response.** Rejected: a crash between the two
leaves a real Razorpay order with no local record, and the local record is what the webhook handler
needs in order to reconcile.

**Evaluate policy, then create the order in a separate transaction.** Rejected: it reopens the
inventory race C6 identifies.

**Return only the first failing reason code.** Rejected by P§7's `reason_codes` array, and it would
make the buyer's recovery a sequence of surprises.

**Let the frontend send the total it displayed, so the backend can compare.** Superficially a
drift check. Rejected: it makes a client-supplied value part of a financial decision, and the
backend already knows both the approved total and the live total — it needs nothing from the client.

**Per-session or per-day spending limits.** Rejected for the MVP as unspecified scope; P§13 defers
configurable policy.

## Consequences

**Enables.** A single auditable choke point for money. Every policy rule is a pure function of a
`TransactionContext`, so all ten are testable without Razorpay, without a model and without HTTP.

**Forecloses.** Any fast path to checkout. Every purchase pays for a live re-read and a lock, which
costs a few milliseconds and buys the correctness property the project is built to demonstrate.

**Costs.** The transaction holds inventory row locks for the duration of policy evaluation. With
30 SKUs and a demo workload this is irrelevant; at scale, evaluation must stay short and must never
call out over the network — which is already required, since the engine has no network access.

## Implementation implications

- `app/policy/policy_engine.py`, `rules.py`, `reason_codes.py`, `schemas.py` — the engine performs
  no I/O; the caller assembles the `TransactionContext` from live reads.
- `app/services/order_service.py` owns the transaction, the locking, and the ordering of steps.
- `app/payments/razorpay_client.py` is the only module importing the Razorpay SDK, is constructed
  from configuration only, and exposes `create_order(order: Order) -> RazorpayOrder`.
- `SPENDING_LIMIT` and `SPENDING_LIMIT_CURRENCY` are typed configuration.
- **M9 tests:** one per rule, in isolation, plus a test that a failing context yields every
  applicable reason code rather than only the first.
- **M10 test:** no Razorpay call is made when policy fails — asserted against a fake client that
  records calls, and the assertion is that the recorder is empty.
- **M11 test:** the checkout configuration returned to the frontend contains the public key id and
  contains neither secret; a response-body scan asserts no configured secret value appears anywhere
  in any API response.
- **M10 test:** two concurrent order creations for the last unit produce one order and one
  `OUT_OF_STOCK`.

## Status

**Accepted, not implemented.** M9, M10 and M11.
