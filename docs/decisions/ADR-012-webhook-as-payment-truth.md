# ADR-012: The Verified Webhook is Payment Truth

**Status:** Accepted, not implemented (2026-08-30)
**Milestone:** M12
**Source references:** `architecture.md` L§24, A§56, P§21, P§22, P§23, P§24, P§25, P§26, P§27, P§28, P§29, P§39 (RZP-04…RZP-07), P§40, F§19, F§20, F§21
**Related open questions:** D7, D8, E7

## Context

P§28 states the rule without qualification:

> The source of truth for payment status is: Verified Razorpay webhook + Database state.
> NOT: Frontend payment-success message. NOT: Claude's statement. NOT: User's statement.

Four properties are specified concretely. Signature verification uses the webhook secret and the
**raw request body** (P§23), and the raw body must be preserved before parsing (P§24). Delivery is
at-least-once, so duplicate events happen and are deduplicated by Razorpay's event id (P§25, P§26).
Arrival order is not business order (P§27). Every processed event writes an audit record (RZP-07).

Two things are left open: which events to subscribe to, and what happens after a failed payment.

## Problem

Define webhook processing so that a payment is recorded exactly when Razorpay says it happened,
exactly once, regardless of delivery order, forgery attempts, retries, or a frontend that claims
success.

## Decision

### The raw body is captured before anything touches it

The route reads `await request.body()` and holds those exact bytes. Verification runs against them.
Parsing happens **only after** verification succeeds. The application never re-serializes the parsed
payload for verification (P§24) — `json.loads` followed by `json.dumps` does not reproduce the
original bytes, and a signature over reproduced bytes proves nothing.

FastAPI's automatic Pydantic body binding is **not** used on this route, because it consumes and
re-encodes the body.

### Verification

HMAC-SHA256 over the raw body using `RAZORPAY_WEBHOOK_SECRET`, compared to the
`X-Razorpay-Signature` header using a **constant-time comparison** (`hmac.compare_digest`). A
non-constant-time comparison leaks signature bytes through timing.

Failure means: return `400`, write a `WEBHOOK_SIGNATURE_REJECTED` audit event, change no payment
state. An unverified webhook is not a webhook; it is an anonymous HTTP request (P§23).

### Deduplication by database constraint

Razorpay's event id is inserted into `webhook_events` under `UNIQUE(provider, event_id)`. A
duplicate raises a unique-violation, which is caught and answered with `200 OK` plus a
`WEBHOOK_DUPLICATE_IGNORED` audit event.

The uniqueness is enforced by the database, not by a "have I seen this?" query, because two
simultaneous deliveries of the same event would both pass a read-then-write check (P§25, P§26).

### Order-independent handling

Events are processed by their semantics, not by arrival order (P§27). Each handler is written as an
idempotent state assertion, not as an increment:

- `payment.captured` → set the payment to `CAPTURED` and the order to `PAYMENT_CONFIRMED`.
- `payment.failed` → set the payment to `FAILED` and the order to `PAYMENT_FAILED`, unless the order
  is already `PAYMENT_CONFIRMED`, in which case log the conflict and change nothing.
- `order.paid` → set the order to `PAYMENT_CONFIRMED` if it is not already.

Applying the same event twice, or applying a late-arriving earlier event after a later one, converges
to the same state. Transitions never move backwards from `PAYMENT_CONFIRMED`.

An event whose `razorpay_order_id` matches no local order is stored with a null `order_id` and status
`RECEIVED`, and answered `200`. It is not an error; it is an event that arrived before its order was
committed, or one belonging to another system sharing the account. It is never dropped, because the
stored row is what makes reconciliation possible.

### Subscribed events

`payment.captured`, `payment.failed`, `order.paid` (closes D7). Every other event type is stored with
status `IGNORED` and answered `200` — recorded, not acted on. Silently discarding unknown events
would make a future subscription change invisible.

### `200` is the default answer

Razorpay retries non-2xx responses. The endpoint returns `200` for: successful processing, a
duplicate, an unknown event type, and an event for an unknown order — all of which are correctly
handled outcomes. It returns `400` only for a failed signature check, and `500` only for a genuine
internal fault where a retry is actually wanted.

### The frontend callback is not truth

Razorpay Checkout's success callback tells the frontend to stop showing a spinner (F§19). It MUST
NOT mark an order paid. The frontend polls `GET /api/orders/{order_id}` for backend state (F§21).
Until a verified webhook arrives the order sits in `PAYMENT_PENDING` and the UI shows
"Payment verification pending" — a real state, not a euphemism.

The agent is bound by the same rule: it may say "your payment was successful" only when
`orders.status` is `PAYMENT_CONFIRMED` (L§24, A§56).

### Payment failure recovery

A failed payment (closes D8) leaves the cart intact and `ACTIVE`, supersedes the approval, marks the
idempotency key `FAILED`, and requires a fresh approval and a fresh key to retry. This is the same
recovery path as price drift (ADR-014), which means one flow is built and tested rather than two.

### Audit

Every webhook writes at least one audit event: `PAYMENT_WEBHOOK_RECEIVED` on arrival, then
`PAYMENT_CONFIRMED`, `PAYMENT_FAILED`, `WEBHOOK_DUPLICATE_IGNORED` or
`WEBHOOK_SIGNATURE_REJECTED`. Audit payloads carry the event id, the event type and the resulting
state — never the secret and never the raw signature.

## Alternatives considered

**Trust the frontend callback and confirm with a webhook later.** Rejected outright by P§28 and
L§24. It would mean showing a buyer a confirmed order that may never be paid.

**Verify by re-serializing the parsed JSON.** Rejected by P§24: key order and whitespace are not
preserved, so the HMAC differs from Razorpay's.

**Deduplicate with an in-memory set of recent event ids.** Rejected: lost on restart, not shared
across processes, and racy.

**Deduplicate by checking for an existing row before inserting.** Rejected: read-then-write has a
race that at-least-once delivery will find. A unique constraint does not.

**Reject events for unknown orders with a `4xx`.** Rejected by P§27: a legitimately early event
would be permanently lost after Razorpay's retries expire.

**Poll Razorpay's API instead of handling webhooks.** Rejected: the project explicitly requires
webhook handling (RZP-04). Polling could serve as a later reconciliation backstop; it is not the
mechanism.

## Consequences

**Enables.** A payment state that is correct under duplicate delivery, out-of-order delivery, forged
requests, and a lying or compromised frontend. It also produces the answer to the specification's
third interview question (P§46) as an actual implementation rather than a claim.

**Forecloses.** Instant confirmation. There is a real window between a buyer completing Checkout and
the webhook arriving, during which the honest answer is "verification pending". The UI shows that
state rather than pretending.

**Costs.** A publicly reachable webhook endpoint, which for local development means a tunnel. The
raw-body requirement means this route cannot use the framework's ordinary body parsing, which is a
standing trap for anyone refactoring it — hence the test below.

## Implementation implications

- `app/api/routes/webhooks.py` — reads the raw body first, verifies, then parses. A comment states
  why, and a test enforces it.
- `app/payments/webhook.py` — `verify_signature(raw_body: bytes, signature: str) -> bool` using
  `hmac.compare_digest`, and one handler per subscribed event type.
- `webhook_events` and `payments` tables per ADR-006; `payments` rows are written **only** from this
  path.
- `RAZORPAY_WEBHOOK_SECRET` is typed configuration, never logged, never returned, never prompted.
- **M12 tests** (P§40 tests 7–9): a valid signature is accepted; an invalid signature returns `400`
  and changes no state; a duplicate event id causes exactly one state transition; an event for an
  unknown order is stored and answered `200`; `payment.failed` arriving after `payment.captured`
  does not un-confirm the order; the frontend callback alone never marks an order paid; a tampered
  body with a valid signature for the original body fails verification.
- **M12 test:** the route function never binds a Pydantic body model — asserted by inspecting the
  route signature, so a well-intentioned refactor that "cleans up" the handler fails the suite.
- Razorpay fixtures live under `backend/tests/fixtures/razorpay/` and are clearly test doubles. No
  fake Razorpay response is ever constructed outside that directory (Phase-5 quality rule).

## Status

**Accepted, not implemented.** M12.
