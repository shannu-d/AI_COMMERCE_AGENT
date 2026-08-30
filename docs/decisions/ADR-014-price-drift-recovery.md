# ADR-014: Price Drift Recovery

**Status:** Accepted, not implemented (2026-08-30)
**Milestone:** Policy rule M9; recovery flow M10; UI M14; end-to-end scenario M15
**Source references:** `architecture.md` R§17 (RULE 12), L§32, L§33, A§27, A§28, A§47, P§11, P§32, P§38 (POLICY-05), P§45, F§16, F§23, F§38
**Related open questions:** D2, D9

## Context

`architecture.md` calls this "the project's flagship failure scenario" and specifies it five times.
P§32:

```
Case = ₹1,499  →  User: "Yes."  →  Database price = ₹1,699
Policy Engine: fetch live price → compare → MISMATCH → POLICY FAIL
→ NO Razorpay order → NO money movement → user notified
→ user reconfirms → fresh approval → fresh idempotency key → Policy PASS → Razorpay order
```

F§38 makes it the closing act of the demo, and gives the reason it matters:

> This single scenario demonstrates that the architecture is not merely a chatbot with a payment
> button.

Every mechanism the other ADRs define exists to make this one path work: catalog authority
(ADR-002), approval binding (ADR-007), exact money (ADR-008), the policy boundary (ADR-011), fresh
keys (ADR-013).

## Problem

Specify the detection, the refusal, the explanation and the recovery precisely enough to implement
and to test — including the direction question the specification leaves open.

## Decision

### Detection

Inside the order-creation transaction, before any Razorpay call, the Policy Engine recomputes the
cart total from `product_variants.price` read **live** and compares it to `approvals.approved_total`
using exact `Decimal` equality (ADR-008).

It never reads `cart_items.unit_price_snapshot`, never reads a value cached earlier in the request,
and never reads anything the model or the client supplied. The snapshot's only role is to let the
system say *what changed*, per line, in the explanation.

### Any difference fails, in either direction

A price **decrease** fails the check exactly as an increase does (closes D2).

The buyer approved ₹1,798. Charging ₹1,698 charges an amount they never authorized. It is a smaller
harm than overcharging and it is the same class of error, and a system that silently deviates
downward has already conceded that the approved figure is advisory. Reconfirming a lower price costs
one message and one click, and the buyer will not object.

This is a deliberate divergence from a narrow reading of P§32 — which illustrates only an increase —
and it is consistent with P§11's stated rule, `Displayed Total != Current Total`, which is inequality
in both directions.

### The refusal

On mismatch, in order:

1. **Roll back the transaction.** No order row, no order items, no inventory mutation.
2. **Do not call Razorpay.** No Razorpay order is created; this is asserted by a test against a
   recording fake, and the assertion is that the recorder is empty.
3. **Mark the idempotency key `FAILED`** (ADR-013). The attempt is over; it is not resumable.
4. **Supersede the approval** — `status = 'SUPERSEDED'` (ADR-007). It authorizes nothing further.
5. **Refresh the cart** to the live prices and **increment `cart_version`**. The buyer's next
   confirmation is against a cart whose displayed prices are true.
6. **Write audit events** `POLICY_FAIL` and `PRICE_CHANGED`, with per-line old and new prices.
7. **Return a structured failure.**

### The failure payload

```json
{
  "error": {
    "code": "PRICE_CHANGED",
    "message": "The price changed before checkout.",
    "details": {
      "approved_total": "1798.00",
      "current_total": "1998.00",
      "currency": "INR",
      "cart_version": 8,
      "changes": [
        { "sku": "CASE-IP16-BLK", "name": "AeroCase Pro",
          "old_unit_price": "1499.00", "new_unit_price": "1699.00", "quantity": 1 }
      ]
    }
  }
}
```

Per-line detail, not just the totals, because "the total went up by ₹200" is not an explanation and
a buyer cannot make a decision from it. The HTTP status is `200` — a policy refusal is a successful
turn with an error body (ADR-010) — so the frontend renders a recovery flow rather than a network
error.

### The explanation

The agent tells the buyer what changed, using the structured `changes` array. It states the old
price, the new price and the new total, and asks whether to proceed. It MUST NOT proceed on its own,
MUST NOT treat the previous approval as still valid (L§33), and MUST NOT round, average or otherwise
soften the number.

The wording is the model's; the numbers come from the payload.

### Recovery

The buyer reconfirms against the **new** cart version. That is an ordinary
`POST /api/cart/approve` — the same endpoint, the same validation, no special case. It produces a
new approval bound to the new version, total and fingerprint, and mints a fresh idempotency key
(ADR-013). `POST /api/orders` then runs the full policy evaluation again, from scratch.

If the price moves a second time, the same path runs a second time. There is no "retry with the
previous approval", and no attempt limit — each cycle is a fresh, fully-validated authorization.

If the buyer declines, the approval becomes `REJECTED` and the cart stays intact.

### The same path serves every policy failure

`OUT_OF_STOCK`, `SPENDING_LIMIT_EXCEEDED` and payment failure recover identically: fail, supersede,
mark the key failed, explain with structured detail, require a fresh approval. One flow is built,
tested and demonstrated rather than four. Only the reason code and the explanatory detail differ.

### After the Razorpay order exists

Once a Razorpay order is created, its amount is final (closes D9). A later catalog price change does
not alter or invalidate it. The guarantee this ADR provides is precise: **no order is ever created at
an amount the buyer did not approve.** It is not a guarantee that the catalog price cannot move
between order creation and payment capture — the Razorpay order fixes the amount at creation, which
is the natural boundary.

## Alternatives considered

**Proceed when the price dropped.** Rejected — see above. The approved figure is either binding or
it is not.

**Tolerate a small delta — say ±₹1 or ±0.5%.** Rejected: any tolerance is an amount the buyer did not
approve, and the threshold would be arbitrary. Exact `Decimal` comparison has no false positives.

**Auto-approve the new total when it is lower and re-ask only when it is higher.** Rejected: it makes
the system's willingness to charge an unapproved amount conditional on the direction, which is a
policy nobody stated and a buyer cannot predict.

**Keep the approval valid and just update the total.** Rejected by A§27, A§28 and P§10. That is the
bug the whole mechanism exists to prevent.

**Re-check the price at cart-view time only, and trust it at order time.** Rejected by RULE 12 and
P§11: the gap between viewing and confirming is exactly where drift occurs.

**Lock prices for the approval window.** A real design used in production systems, and out of scope
here: it would require a price-reservation mechanism the specification does not describe, and it
would hide the failure this project is built to demonstrate.

## Consequences

**Enables.** The flagship demonstration, end to end and honestly: an approval that becomes stale, a
refusal that is enforced by application code, a Razorpay call that never happens, an explanation
grounded in real numbers, and a clean recovery. It is also the strongest available evidence that the
model is not on the money path — the model is entirely uninvolved in the detection and the refusal.

**Forecloses.** Any "close enough" checkout. A catalog price change during a buyer's session always
costs a reconfirmation.

**Costs.** An extra round-trip on every drift event, and a UI state that must be built and tested
(FE-05). Both are the deliverable, not overhead.

## Implementation implications

- The price rule is one of the ten in `app/policy/rules.py`, independently unit-testable
  (POLICY-05).
- `PolicyDecision` carries `validated_total`; the order path assembles `changes` by comparing live
  prices to `cart_items.unit_price_snapshot` per line.
- Superseding the approval, refreshing the cart, incrementing the version and failing the key all
  happen in the failure handler, in one transaction, so a crash cannot leave a superseded approval
  with a live key.
- Audit events `POLICY_FAIL` and `PRICE_CHANGED` carry the per-line detail.
- **M9 test (POLICY-05):** approved ₹1,499, live ₹1,699 → `FAIL` with `["PRICE_CHANGED"]`.
- **M9 test:** approved ₹1,499, live ₹1,299 → `FAIL` with `["PRICE_CHANGED"]`. The decrease case is
  a first-class test, not a footnote.
- **M10 test:** on drift, the recording Razorpay fake receives **zero** calls; no order row exists;
  the key is `FAILED`; the approval is `SUPERSEDED`; `cart_version` has incremented.
- **M15 test (TEST-03, the flagship):** full end-to-end — recommend → cart → approve → mutate the
  catalog price → attempt order → `PRICE_CHANGED` → re-approve → order created → Razorpay test-mode
  order exists → webhook confirms. This test is the project's headline acceptance criterion.
- The catalog price mutation in the test is a direct database update, mirroring what a merchant would
  do, not a special test hook in application code.

## Status

**Accepted, not implemented.** The rule lands in M9, the recovery flow in M10, the UI in M14, and the
end-to-end scenario in M15.
