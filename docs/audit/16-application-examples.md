# 16 — Application Examples

Seven scenarios. Where a scenario was executed during this audit, the values shown are **real
observed output**, not illustration. Each is labelled.

---

## Example 1 — Normal purchase · ✅ EXECUTED LIVE

**Buyer:** *"I need a case for my iPhone 16 under 1500"*

```
1. INTENT EXTRACTION  (Groq, openai/gpt-oss-120b)
   The model returns an intent, not an answer:
     category    : phone_case
     device      : "iPhone 16"        <- a PHRASE, never a fact
     budget      : 1500.00            <- parsed with parse_float=Decimal

2. COMPATIBILITY RESOLUTION  (deterministic, no model)
   "iPhone 16" -> normalize_token() -> compatibility_targets -> "iphone_16"
   Unresolvable would mean ASK THE BUYER. It never guesses.

3. CATALOG QUERY  (PostgreSQL)
   Only the category is pushed into SQL. Budget and text are deliberately not,
   so the no-match path still has real products to offer.

4. HARD CONSTRAINTS  (eliminate, never score)
   merchant, category, compatibility, budget, inventory
   -> 3 survivors

5. RANKING  (pure, deterministic, Decimal to 6 places)
   backend log: recommendation computed alternatives=0 candidates=3
                label='phone_case' outcome='EXACT_MATCH' profile='default'

6. RESPONSE
```

| Rank | Product | Variant | Price | Stock | Reason (engine-authored) |
| --- | --- | --- | --- | --- | --- |
| 1 | AeroCase Pro | Black | ₹999.00 | IN_STOCK | Best overall |
| 2 | AeroCase Pro | Blue | ₹999.00 | IN_STOCK | Best price |
| 3 | ShieldCase Premium | Black | ₹1,299.00 | LOW_STOCK | Closest match to your requirements |

Ranks 1 and 2 tie on score *and* price, so the tie broke on SKU — the third sort key.

```
7. CART        POST /api/cart/items  -> cart_version 2, total "999.00"  (server-computed)
8. APPROVAL    POST /api/cart/approve -> APPROVED, approved_total "999.00", TTL 15 min
               idempotency_key ISSUED BY THE APPLICATION
9. ORDER       POST /api/orders -> 201 ORDER_CREATED
               total_amount 999.00 | total_amount_minor 99900 | razorpay_order_id null
```

The internal order commits **before** the provider is called, so it is visible and retryable.

---

## Example 2 — Budget constraint · ✅ EXECUTED LIVE

**Buyer:** *"a phone case under ₹1500"*

Budget is a **hard constraint first, a score second**:

1. **Elimination.** Anything above ₹1,500 leaves the candidate set. It is not ranked low — it is
   *gone*. A product at ₹1,899 cannot appear however well it scores elsewhere.
2. **Scoring.** Among survivors, R§8 uses the stated budget as the denominator, so a product priced
   exactly at the budget scores `0.0` on price — deliberately.
3. **Alternatives.** An over-budget product may return as a *labelled alternative*, re-scored with
   the budget removed (or the clamp would flatten them all to zero and lose their order).

Observed: all three results fell under ₹1,500; ShieldCase at ₹1,299 ranked third despite being in
stock and compatible, because price weighs against it.

---

## Example 3 — Incompatible product · ✅ COVERED BY TESTS

The catalogue deliberately contains an **iPhone 15 case** that must never appear for an iPhone 16
query.

```
requirement.compatibility_target : ResolvedTarget("iphone_16")   <- a TYPE, not a string
rule lookup  : target_type IN ('phone_model', 'device')
iPhone-15-only case -> no matching rule -> ELIMINATED
```

Two structural guarantees:

- **Compatibility is never relaxable.** A case for a different phone is a *wrong answer*, not a
  lesser one — so it is never offered as an "alternative" either.
- `apply_hard_constraints` **takes no weight profile**, so there is no configuration in which a
  cheaper incompatible product outranks a compatible one.

Tests: `test_a_cheaper_incompatible_product_is_never_a_candidate`,
`test_an_incompatible_product_is_never_offered_as_an_alternative`.

---

## Example 4 — Out-of-stock product · ✅ PARTLY OBSERVED LIVE

Inventory eliminates before ranking, and is **never relaxable** (RULE 5 — an alternative nobody can
buy is not an alternative).

| Condition | Outcome |
| --- | --- |
| `stock_quantity = 0` | eliminated |
| **no inventory row at all** | eliminated — *not* assumed available |
| stock below requested quantity | eliminated |
| stock at or below `LOW_STOCK_THRESHOLD` | survives, flagged `LOW_STOCK` |

Observed live: ShieldCase Premium returned with `LOW_STOCK` and rendered a "Low stock" badge — it
remains purchasable, and the buyer is told.

If a variant sells out between recommendation and order, `_rule_6_inventory` catches it inside the
order transaction and the order is refused with `OUT_OF_STOCK`.

---

## Example 5 — PRICE DRIFT · ✅ EXECUTED LIVE, BOTH DIRECTIONS (flagship)

Executed against the live database during this audit.

```
1. Cart built           total "999.00", cart_version 2
2. Buyer authorizes     APPROVED at "999.00"
3. Merchant changes product_variants.price   <- the authoritative value
4. Order attempted      policy re-reads price LIVE inside the order transaction
```

| Direction | Price change | HTTP | Code | Reason codes |
| --- | --- | --- | --- | --- |
| **Upward** | ₹999.00 → ₹1,199.00 | **422** | `POLICY_FAILED` | `['INVALID_CART', 'PRICE_CHANGED']` |
| **Downward** | ₹999.00 → ₹799.00 | **422** | `POLICY_FAILED` | `['INVALID_CART', 'PRICE_CHANGED']` |

**Neither direction produced an order. Neither could charge an unapproved amount.**

The downward case is the one most systems get wrong. A *cheaper* price still invalidates the
approval, because the buyer authorized **one exact total** and the system will not substitute a
different one — not even a more favourable one — without fresh consent.

The engine reports *all* failing rules rather than the first, which is why two codes appear.

**Recovery:** drift surfaces in `price_changes[]`, the buyer re-approves at the new total, and a
fresh idempotency key is issued. The prior approval becomes `SUPERSEDED` — observed live.

The catalogue price was restored to ₹999.00 and re-verified after the test.

---

## Example 6 — Failed payment · ⚠️ INTEGRATION TESTED ONLY

```
Razorpay -> POST /api/webhooks/razorpay   {"event": "payment.failed", ...}

1. raw_body = await request.body()          <- captured BEFORE parsing
2. HMAC-SHA256 over raw bytes, hmac.compare_digest
3. only then parse
4. payments row -> FAILED
5. orders row   -> PAYMENT_FAILED
6. audit        -> PAYMENT_FAILED
```

The order stays visible and retryable; the buyer recovers through the same path as price drift.

**Blocked from live verification:** with no provider order id, a real `payment.failed` cannot
correlate to an order. Signature verification, deduplication and persistence *were* verified live —
only the state transition was not.

---

## Example 7 — Duplicate webhook · ✅ EXECUTED LIVE

Run against a freshly started backend using signatures generated from the real webhook secret:

| Delivery | Signature | Response |
| --- | --- | --- |
| 1 | tampered | **`400` `{"status":"rejected"}`** — nothing parsed, nothing stored |
| 2 | valid | **`200` `{"status":"received"}`** — event persisted |
| 3 | valid, **same `event_id`** | **`200` `{"status":"ignored"}`** — no second effect |

Deduplication is a `UNIQUE(provider, event_id)` constraint, not a read-then-write check, so two
simultaneous deliveries cannot both pass a check and both act.

Audit trail: `WEBHOOK_SIGNATURE_REJECTED`, `PAYMENT_WEBHOOK_RECEIVED`, `WEBHOOK_DUPLICATE_IGNORED`.

---

## What these examples demonstrate

Every example traces the same invariant:

> **LLM proposes → application validates → user authorizes → Razorpay executes → system audits.**

The model contributed exactly two things in Example 1: a category guess and the phrase "iPhone 16".
Every price, every stock level, every compatibility judgement, every rank, every total and the
decision to permit the order came from deterministic code reading the database.
