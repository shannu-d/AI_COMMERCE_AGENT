# ADR-007: The Approval Model

**Status:** Accepted, not implemented (2026-08-30)
**Milestone:** M8
**Source references:** `architecture.md` L§21, A§9 (AGENT-09), A§26, A§27, P§9, P§10, P§38 (POLICY-04), F§14, F§15
**Related open questions:** C3 (BLOCKING), D1, D5 (BLOCKING)

## Context

P§9 draws the line between a question and an authorization:

> The system must not interpret "Show me the cart" as approval. Similarly: "How much is it?" is not
> approval.

P§10 says approval belongs to a cart ID, a cart version, a user/session and an approved total, and
that a changed cart invalidates it. A§26 explains why: without that binding, "the agent could
accidentally associate the approval with the wrong cart".

The unresolved part is authorship. `request_approval()` is listed as a model-callable tool (L§10,
A§8, A§14) while approval is defined everywhere else as an explicit human act that the application
records. If the tool records approval, the model can approve on the buyer's behalf — which the
invariant forbids. A§9 also asks for "expired/stale approval handling" without giving an expiry.

## Problem

Who can create an approval, exactly what does an approval authorize, when does it stop being valid,
and how is all of that enforced in code rather than in prompt wording?

## Decision

### Only a user action creates an approval

`POST /api/cart/approve`, originating from a buyer's deliberate action in the UI, is the **only**
path that writes a row with `status = 'APPROVED'` (closes D5). It carries the `cart_id` and the
`cart_version` the buyer was looking at, so an approval submitted against a stale view is detectable
rather than silently applied to whatever the cart is now.

`request_approval()` remains available to the model but is **re-scoped to a state transition with no
authority**. It may only move the session's conversation state to `WAITING_FOR_APPROVAL` and surface
the authoritative cart for confirmation. It writes an approval row with `status = 'PENDING'` and
nothing else. It cannot write `APPROVED`; the service method it calls does not accept that value.
This is enforced by the type system and by a test, not by the system prompt.

### What an approval binds to

Five things, all recorded on the row:

| Bound to | Why |
| --- | --- |
| `session_id` | An approval from one conversation cannot authorize another |
| `cart_id` | An approval is for a specific cart |
| `cart_version` | The cart's exact state at the moment of approval (A§27, F§13) |
| `approved_total` + `currency` | The amount the buyer actually saw and agreed to |
| `items_fingerprint` | SHA-256 over the canonical list of `(variant_id, quantity, unit_price)` tuples, sorted by `variant_id` |

The fingerprint exists because a total is not a composition. Two different carts can reach ₹1,798 —
swapping a ₹1,499 case plus a ₹299 guard for a ₹1,299 case plus a ₹499 twin-pack leaves the total
identical and the order completely different. `cart_version` catches this in the normal case; the
fingerprint catches it unconditionally, including after any future change that lets a version be
reused.

### Statuses

`PENDING` → `APPROVED` | `REJECTED` | `EXPIRED` | `SUPERSEDED`

| Status | Meaning |
| --- | --- |
| `PENDING` | The agent has asked. The buyer has not answered. Authorizes nothing. |
| `APPROVED` | The buyer authorized this exact cart version, total and composition. |
| `REJECTED` | The buyer declined. Terminal. |
| `EXPIRED` | The TTL elapsed before use. Terminal. |
| `SUPERSEDED` | A later approval replaced it, or the cart changed underneath it. Terminal; `superseded_by_id` points forward when a successor exists. |

Only `APPROVED` authorizes anything, and only while it is unexpired and un-superseded.

### Invalidation

An `APPROVED` approval becomes `SUPERSEDED` **immediately and unconditionally** when any of these
occurs, transitioned by the same code path that makes the change:

1. `carts.version` increments for any reason — item added, removed, quantity changed.
2. A cart refresh finds an authoritative unit price different from `unit_price_snapshot`, in
   **either direction** (closes D2). A price drop also invalidates. The buyer approved a specific
   total; charging a different one, cheaper or not, is charging an amount that was never authorized.
   Reconfirming a lower price costs one click and one message.
3. The recomputed `items_fingerprint` no longer matches.
4. A fresh approval is recorded for the same cart.

### Expiry

**15 minutes** from `approved_at` (closes D1). `architecture.md` requires expiry handling without
naming a value; 15 minutes is long enough for a buyer to finish a Razorpay Checkout flow and short
enough that a forgotten tab does not authorize a purchase an hour later. `expires_at` is stored
explicitly rather than computed at read time, so changing the TTL never retroactively revives or
kills an existing approval. Expiry is evaluated at the moment of use, by the Policy Engine — a
sweeper job is an optimization, never the mechanism.

### What approval is not

Approval is **not** authorization to charge whatever the cart later becomes. It is a claim about a
specific past state, and the Policy Engine re-validates that claim against live data immediately
before order creation (ADR-011, ADR-014). An approval that passes every check above can still fail
policy, because policy re-reads prices and stock while approval only remembers them.

### Relationship to the other two state machines

Three enums, each owned by one table, none derived from another (closes C7):

| Enum | Lives on | Example values |
| --- | --- | --- |
| Conversation state | `sessions.conversation_state` | `CART_PROPOSED`, `WAITING_FOR_APPROVAL`, `POLICY_VALIDATION` |
| Approval status | `approvals.status` | `PENDING`, `APPROVED`, `SUPERSEDED` |
| Order state | `orders.status` | `ORDER_CREATED`, `PAYMENT_CONFIRMED` |

The conversation state is display and orchestration state; it is never read by the Policy Engine.
The Policy Engine reads `approvals.status` and `orders.status`. A session whose conversation state
says `APPROVED` while no `APPROVED` approval row exists is a bug in the agent, and it authorizes
nothing.

## Alternatives considered

**Let `request_approval()` record approval when the model judges that the buyer consented.**
Rejected. It puts the authorization signal inside the probabilistic component, making "yeah I was
just asking" indistinguishable from "yes, buy it" — precisely the confusion P§9 forbids.

**Bind approval to the total only.** Rejected: two different carts can share a total.

**Bind approval to the cart without a version.** Rejected by A§27 and F§13, and it is the exact
mechanism the price-drift scenario needs.

**No expiry — an approval is valid until superseded.** Rejected: A§9 requires expiry handling, and
an approval is a statement about a moment. Prices and stock move.

**Only invalidate on a price increase.** Tempting, and wrong. See invalidation rule 2.

**Keep approval state in the session object in memory.** Rejected by C3: it would be lost on
restart, invisible to other processes, and unauditable — for the one record that says a human
authorized a payment.

## Consequences

**Enables.** A purchase authorization that is provable after the fact: which session, which cart,
which version, which total, which items, at which instant. It makes the price-drift demonstration
work, because there is a durable prior claim for live data to contradict.

**Forecloses.** Fully autonomous purchasing. The agent can never complete a purchase without a human
action, which is the point.

**Costs.** More round-trips: change the cart, re-approve. A buyer who edits a cart after approving
must approve again. That friction is the feature.

## Implementation implications

- `approvals` table exactly as specified in ADR-006, including the partial unique index
  `UNIQUE(cart_id, cart_version) WHERE status = 'APPROVED'`.
- `ApprovalService.request(session, cart) -> Approval` — writes `PENDING` only. There is no
  parameter by which it can write `APPROVED`.
- `ApprovalService.approve(session, cart_id, cart_version) -> Approval | ApprovalError` — callable
  only from the `POST /api/cart/approve` route. Rejects a `cart_version` that is not current, with
  reason code `CART_VERSION_STALE`.
- `ApprovalService.supersede(cart, reason)` — invoked by `CartService` on every mutation and by
  every price refresh that finds a change. Writes an `APPROVAL_SUPERSEDED` audit event.
- `items_fingerprint` is computed by one shared function used by both the writer and the Policy
  Engine, over a canonical JSON serialization with sorted keys and `Decimal` amounts rendered as
  fixed-scale strings. A second implementation would eventually disagree with the first.
- Approval TTL is a typed configuration value, `APPROVAL_TTL_SECONDS`, defaulting to 900.
- **M8 exit tests:** a stale `cart_version` is rejected; a cart mutation supersedes an existing
  approval; an expired approval fails policy with `APPROVAL_REQUIRED`; a price *decrease* supersedes;
  `request_approval()` cannot produce an `APPROVED` row; two approvals of the same cart version
  cannot both be `APPROVED`.

## Status

**Accepted, not implemented.** M8, on the tables from ADR-006 (M6).
