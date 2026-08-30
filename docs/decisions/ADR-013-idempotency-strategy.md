# ADR-013: Idempotency Strategy

**Status:** Accepted, not implemented (2026-08-30)
**Milestone:** M10 (order creation); M12 (webhook deduplication)
**Source references:** `architecture.md` A§46, A§47, A§58 (AGENT-12), P§14, P§15, P§16, P§25, P§26, P§34, P§45
**Related open questions:** D4 (BLOCKING)

## Context

P§15 gives the scenario: a buyer clicks Pay, then clicks it again. Without protection, two orders.
A§46 adds a second source of duplication — the agent producing the same order request twice.
P§16 and A§47 require a **fresh** idempotency key after price-drift recovery, so that the retry is
not mistaken for a replay of the abandoned attempt.

What the document never says is who mints the key, what it covers, and how long it lives (D4).

## Problem

Define key minting, key scope, key lifetime, and the exact behaviour on replay — including the case
where the second request arrives while the first is still in flight.

## Decision

### The backend mints the key, at approval time

When `POST /api/cart/approve` records an `APPROVED` approval, the same transaction creates an
`idempotency_keys` row bound to that approval's exact state, and the key value is returned to the
client alongside the approval. The client presents it on `POST /api/orders`.

The backend mints it, not the client, because the key must be **derived from the state it protects**.
A client-chosen key protects only against that client's own retries; it cannot express "this is the
same logical transaction as the one already approved", and a buggy or hostile client could reuse one
key across genuinely different carts.

### Scope

The key is bound to the tuple:

```
(session_id, cart_id, cart_version, approved_total, currency)
```

Any change to any element yields a different key. A cart mutation increments `cart_version`
(ADR-006) and supersedes the approval (ADR-007), so the next approval mints a new key — which is
exactly the "fresh idempotency key" P§16 requires, obtained as a consequence of the approval rules
rather than as a separate mechanism anyone has to remember.

The stored `key` value is a UUIDv4, not a hash of the tuple. The tuple is stored in its own columns
for auditing and for the replay check; hashing it into the key would make two distinct approvals of
an identically-priced identical cart collide, and those are two different authorizations.

`scope` is `ORDER_CREATION`. Webhook deduplication uses a different mechanism (below) because it
deduplicates an external event, not a local operation.

### Lifetime

**24 hours** from creation (closes D4). Comfortably longer than the 15-minute approval TTL
(ADR-007), so a key always outlives the approval it protects and a late duplicate submission still
finds a stored result rather than a clean slate. `expires_at` is stored explicitly, so changing the
policy never retroactively alters an existing key. Expired keys are eligible for deletion; expiry is
evaluated at use.

### The three-state lifecycle

`RESERVED` → `COMPLETED` | `FAILED`

**Reserve.** `POST /api/orders` claims the key by moving it to `RESERVED` with a conditional update
inside its transaction. If the row is already `RESERVED`, another request is in flight and this one
returns `409 Conflict` with `ORDER_IN_PROGRESS` — it does not wait, and it does not proceed. The
double-click case is a race, and a race must be lost cleanly rather than resolved by whoever arrives
second.

**Complete.** On success the key becomes `COMPLETED`, `completed_at` is set, and
`response_snapshot` stores the exact response body that was returned. `orders.idempotency_key_id` is
`NOT NULL UNIQUE`, so the database itself refuses a second order for the same key. A replay against
a `COMPLETED` key returns the stored snapshot verbatim with `200` — the same answer, not a new
order (P§15, P§34).

**Fail.** On policy failure or an unrecoverable error the key becomes `FAILED`. A `FAILED` key is
terminal and is never retried: the buyer must obtain a fresh approval, which mints a fresh key. This
is the same path as price drift (ADR-014) and payment failure (ADR-012), so there is one recovery
flow rather than three.

### Why the database enforces it

`idempotency_keys.key` is `UNIQUE` and `orders.idempotency_key_id` is `UNIQUE`. Two concurrent
requests cannot both create an order under one key even if both pass every application-level check,
because the second insert violates a constraint. Application logic makes the common case pleasant;
the constraint makes the rare case correct.

### Webhook deduplication is a separate mechanism

Order idempotency protects a **local operation** initiated by a client. Webhook deduplication
prevents reprocessing an **external event** (P§25, P§26). They share a purpose and nothing else, so
they are separate: `webhook_events` with `UNIQUE(provider, event_id)` (ADR-012). Forcing both
through one table would mean a schema serving two different key spaces and two different lifetimes.

### What idempotency does not do

It does not make policy evaluation idempotent, and it must not. Every `POST /api/orders` that does
not hit a `COMPLETED` key runs the full policy evaluation against live data. A replay returns the
stored result; a new attempt is fully re-validated. Caching a `PASS` would defeat the freshness rule
that ADR-011 and ADR-014 are built on.

## Alternatives considered

**Client-generated keys, the way Stripe's API works.** Standard, and appropriate for a public API
where the client owns the retry loop. Rejected here because this backend also owns the approval that
defines the transaction, so it can derive a stronger binding than a client can — and a client-chosen
key can be reused across different carts.

**Key = hash of the binding tuple.** Rejected: two sequential approvals of an unchanged cart would
produce the same key, so a legitimate second purchase of the same items at the same price would be
silently swallowed as a replay.

**Wait for the in-flight request instead of returning `409`.** Rejected: it turns a fast failure into
a held connection with a timeout to tune, and the client has nothing useful to do with the delay.
`409` plus a poll of the order is simpler and honest.

**Retry a `FAILED` key.** Rejected: a key is bound to an approval, and a failure means the approval's
premises no longer hold. Re-approval is the correct recovery, and it mints a fresh key exactly as
P§16 requires.

**Deduplicate orders by cart id alone.** Rejected: it forbids a buyer from ever ordering the same
cart contents twice, and it does not express the version binding.

## Consequences

**Enables.** The duplicate-request scenario (P§34, TEST 6) passes structurally: one logical order,
whatever the client does. Recovery paths converge — price drift, payment failure and policy failure
all end at "get a fresh approval", which mints a fresh key.

**Forecloses.** Resuming a failed attempt in place. Every failure costs the buyer one confirmation
click. That is deliberate: an authorization that survives its own failure is an authorization
nobody explicitly gave.

**Costs.** One extra table and one extra round of state management in the order path. The
`response_snapshot` column stores a copy of a response body, which is duplication accepted for the
sake of returning byte-identical replays.

## Implementation implications

- `idempotency_keys` per ADR-006, with `UNIQUE(key)`; `orders.idempotency_key_id NOT NULL UNIQUE`.
- `IdempotencyService.mint(approval) -> IdempotencyKey` — called only from the approval path.
- `IdempotencyService.claim(key) -> Claimed | AlreadyCompleted(snapshot) | InProgress | Expired` —
  a single conditional `UPDATE ... WHERE status = 'RESERVED' IS NOT TRUE` so the claim is atomic
  rather than a read followed by a write.
- `IDEMPOTENCY_TTL_SECONDS` typed configuration, default 86400.
- `POST /api/orders` requires the key; a missing key is `VALIDATION_ERROR`, never an unprotected
  order.
- **M10 tests** (AGENT-12, P§40 TEST 6): the same request twice yields exactly one order and two
  identical responses; two concurrent requests yield one order and one `409`; a key whose approval
  was superseded is rejected; an expired key is rejected; a `FAILED` key cannot be retried; the
  database rejects a second order for one key even when application checks are bypassed in the test.
- **M10 test:** after a price-drift failure and re-approval, the new key differs from the old one and
  the old key is `FAILED`.

## Status

**Accepted, not implemented.** M10 for order idempotency; M12 for webhook deduplication.
