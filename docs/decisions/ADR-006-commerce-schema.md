# ADR-006: Commerce Schema (Phase 2)

**Status:** Accepted, not implemented (2026-08-30)
**Milestone:** M6 — deliberately **not** part of M1
**Source references:** `architecture.md` D§36, D§37, D§39, A§26, A§27, A§38, P§5, P§10, P§15, P§16, P§25–P§29, P§30, P§RZP-07, F§12, F§13
**Related open questions:** C1 (BLOCKING), C2, C3 (BLOCKING), C5, C6, C7, D1, D4, E7

## Context

`architecture.md` specifies the seven catalog tables down to the index. It names the commerce tables
and stops. D§36 lists `cart`, `cart_items`, `orders`, `order_items`, `payments`, `audit_events` as
"future" and instructs that they not be built in the first catalog milestone. P§29 then sketches
four columns for orders and five for payments, and that is the entirety of the column-level guidance
for the money path.

Meanwhile the Policy Engine reads approval state, cart version, live price and live inventory
(P§5, P§6); idempotency must survive across requests (P§15, P§16); webhook deduplication needs a
store of processed event IDs (P§26); the audit log is a MUST-WORK component (A§40); and A§38
explicitly defers the session persistence strategy. Four tables the money path cannot work without —
`approvals`, `idempotency_keys`, `webhook_events`, `sessions` — are never named as tables at all.

There is also a build-order disagreement: D§36/D§39 forbid commerce tables in the first milestone,
while F§37 sequences cart work before the frontend without saying when the tables arrive.

## Problem

Define every commerce table at column level, with constraints, before any code on the money path is
written — and settle where in the milestone sequence they land.

## Decision

### Ordering

The commerce schema is its own milestone, **M6**, landing after the read-only Agent Runtime (M5) and
immediately before the Cart Service (M7). This satisfies both instructions: the first catalog
milestone stays catalog-only as D§36/D§39 require, and the tables exist before the cart work F§37
sequences. **No commerce table is created in M1.**

### Conventions

Inherited from Phase 1 without exception: `UUID` primary keys via `gen_random_uuid()`, `TIMESTAMPTZ`
timestamps, explicit foreign keys, `NUMERIC(12,2)` for money with an explicit `currency` column
alongside every amount, `JSONB` constrained to objects, and `CHECK` constraints on every enumerated
string column.

### Identity

**Session-only. There is no `users` table** (closes C2). P§5's policy input names a `user_id`; it
maps to `session_id`. Introducing authentication later means adding `users` and a nullable
`user_id` on `sessions`, which is a smaller change than carrying an unused identity model now.

### The eleven tables

#### `sessions`

| Column | Type | Notes |
| --- | --- | --- |
| `id` | UUID PK | the `session_id` the API returns; server-minted, never client-chosen |
| `merchant_id` | UUID NOT NULL → `merchants.id` | |
| `conversation_state` | VARCHAR(48) NOT NULL, CHECK against the agent state enum | default `NEW_SESSION` |
| `intent` | JSONB NOT NULL DEFAULT `'{}'` | accumulated structured intent across turns (A§37) |
| `created_at`, `updated_at`, `last_seen_at` | TIMESTAMPTZ NOT NULL | |

Persisted in PostgreSQL, closing C3. In-memory session state would make the price-drift and
duplicate-request scenarios untestable across processes, and would put the approval record — the
authorization artefact — in volatile memory.

#### `session_messages`

A§38 lists conversation history as session state without giving it a home. A growing JSONB column is
awkward to append to and unbounded; a table is the ordinary answer.

| Column | Type | Notes |
| --- | --- | --- |
| `id` | UUID PK | |
| `session_id` | UUID NOT NULL → `sessions.id` ON DELETE CASCADE | |
| `sequence` | INTEGER NOT NULL | monotonic within the session |
| `role` | VARCHAR(16) NOT NULL, CHECK IN (`user`, `assistant`, `tool`) | |
| `content` | TEXT NULL | |
| `tool_payload` | JSONB NULL | tool call or tool result, structured |
| `created_at` | TIMESTAMPTZ NOT NULL | |

`UNIQUE(session_id, sequence)`. Secrets and API keys are never written here (L§45).

#### `carts`

| Column | Type | Notes |
| --- | --- | --- |
| `id` | UUID PK | |
| `merchant_id` | UUID NOT NULL → `merchants.id` | |
| `session_id` | UUID NOT NULL → `sessions.id` | |
| `status` | VARCHAR(24) NOT NULL, CHECK IN (`ACTIVE`, `ORDERED`, `ABANDONED`) | |
| `version` | INTEGER NOT NULL DEFAULT 1, CHECK ≥ 1 | F§13's `cart_version` |
| `currency` | VARCHAR(3) NOT NULL | |
| `subtotal_amount`, `total_amount` | NUMERIC(12,2) NOT NULL DEFAULT 0, CHECK ≥ 0 | **backend-computed only** |
| `created_at`, `updated_at` | TIMESTAMPTZ NOT NULL | |

Partial unique index `UNIQUE(session_id) WHERE status = 'ACTIVE'` — one active cart per session.

**Versioning rule.** `version` increments on **any** change to the cart's composition or to its
authoritative total: item added, removed, quantity changed, or a refresh that finds a different
authoritative price. It never decrements and is never reset. This is the value the approval binds
to (A§27, F§13).

#### `cart_items`

| Column | Type | Notes |
| --- | --- | --- |
| `id` | UUID PK | |
| `cart_id` | UUID NOT NULL → `carts.id` ON DELETE CASCADE | |
| `variant_id` | UUID NOT NULL → `product_variants.id` ON DELETE RESTRICT | |
| `quantity` | INTEGER NOT NULL, CHECK > 0 | |
| `unit_price_snapshot` | NUMERIC(12,2) NOT NULL, CHECK ≥ 0 | the price when last refreshed |
| `line_total` | NUMERIC(12,2) NOT NULL, CHECK ≥ 0 | |
| `currency` | VARCHAR(3) NOT NULL | |
| `created_at`, `updated_at` | TIMESTAMPTZ NOT NULL | |

`UNIQUE(cart_id, variant_id)`.

`unit_price_snapshot` is **display and drift-detection state, never authority**. The authoritative
price is always re-read from `product_variants` (RULE 6, RULE 12). The snapshot exists precisely so
that drift can be detected and explained to the buyer as "was ₹1,499, now ₹1,799".

#### `approvals`

The table `architecture.md` requires (P§10, POLICY-04) and never defines. Detailed in ADR-007.

| Column | Type | Notes |
| --- | --- | --- |
| `id` | UUID PK | |
| `session_id` | UUID NOT NULL → `sessions.id` | |
| `cart_id` | UUID NOT NULL → `carts.id` | |
| `cart_version` | INTEGER NOT NULL | the version approved, not the current one |
| `approved_total` | NUMERIC(12,2) NOT NULL, CHECK ≥ 0 | |
| `currency` | VARCHAR(3) NOT NULL | |
| `items_fingerprint` | CHAR(64) NOT NULL | SHA-256 over the canonical item tuple list |
| `status` | VARCHAR(16) NOT NULL, CHECK IN (`PENDING`, `APPROVED`, `REJECTED`, `EXPIRED`, `SUPERSEDED`) | |
| `superseded_by_id` | UUID NULL → `approvals.id` | |
| `created_at` | TIMESTAMPTZ NOT NULL | |
| `approved_at` | TIMESTAMPTZ NULL | |
| `expires_at` | TIMESTAMPTZ NOT NULL | |

Partial unique index `UNIQUE(cart_id, cart_version) WHERE status = 'APPROVED'` — a given cart version
can be approved at most once. `CHECK (status <> 'APPROVED' OR approved_at IS NOT NULL)`.

#### `idempotency_keys`

Detailed in ADR-013.

| Column | Type | Notes |
| --- | --- | --- |
| `id` | UUID PK | |
| `key` | VARCHAR(128) NOT NULL UNIQUE | the value clients present |
| `scope` | VARCHAR(32) NOT NULL, CHECK IN (`ORDER_CREATION`) | |
| `session_id` | UUID NOT NULL → `sessions.id` | |
| `cart_id` | UUID NOT NULL → `carts.id` | |
| `cart_version` | INTEGER NOT NULL | |
| `approved_total` | NUMERIC(12,2) NOT NULL | |
| `currency` | VARCHAR(3) NOT NULL | |
| `status` | VARCHAR(16) NOT NULL, CHECK IN (`RESERVED`, `COMPLETED`, `FAILED`) | |
| `response_snapshot` | JSONB NULL | what a replay returns |
| `created_at`, `expires_at` | TIMESTAMPTZ NOT NULL | |
| `completed_at` | TIMESTAMPTZ NULL | |

The key→order link is held **only** on `orders.idempotency_key_id`, so the two tables do not form a
foreign-key cycle. A replay finds its order by querying orders on that column.

#### `orders`

| Column | Type | Notes |
| --- | --- | --- |
| `id` | UUID PK | **this is the internal order id** of P§18/P§29 |
| `merchant_id` | UUID NOT NULL → `merchants.id` | |
| `session_id` | UUID NOT NULL → `sessions.id` | |
| `cart_id` | UUID NOT NULL → `carts.id` | |
| `cart_version` | INTEGER NOT NULL | the version that was ordered |
| `approval_id` | UUID NOT NULL → `approvals.id` | **NOT NULL — an order cannot exist without an approval** |
| `idempotency_key_id` | UUID NOT NULL UNIQUE → `idempotency_keys.id` | one order per key |
| `status` | VARCHAR(32) NOT NULL, CHECK against the order state enum | |
| `currency` | VARCHAR(3) NOT NULL | |
| `subtotal_amount`, `total_amount` | NUMERIC(12,2) NOT NULL, CHECK ≥ 0 | |
| `total_amount_minor` | BIGINT NOT NULL, CHECK ≥ 0 | the exact integer sent to Razorpay (ADR-008) |
| `razorpay_order_id` | VARCHAR(64) NULL UNIQUE | null until Razorpay accepts the order |
| `created_at`, `updated_at` | TIMESTAMPTZ NOT NULL | |

The `approval_id NOT NULL` constraint is the invariant expressed as schema: **the database itself
refuses to store an unapproved order.**

**Order state enum:** `ORDER_CREATED` → `RAZORPAY_ORDER_CREATED` → `PAYMENT_PENDING` →
`PAYMENT_CONFIRMED`, with failure states `PAYMENT_FAILED`, `ORDER_FAILED`, `CANCELLED`.

P§30's list begins earlier — `CART`, `PENDING_APPROVAL`, `APPROVED`, `POLICY_VALIDATED` — but those
describe states in which **no order row exists yet**. They are cart, approval and policy states, and
they live there. This closes C7: two enums, not one. The agent's conversation state (A§25) is a
third, on `sessions`. The mapping is recorded in ADR-007 and ADR-011 and neither enum is ever
derived from the other.

#### `order_items`

| Column | Type | Notes |
| --- | --- | --- |
| `id` | UUID PK | |
| `order_id` | UUID NOT NULL → `orders.id` ON DELETE RESTRICT | |
| `variant_id` | UUID NOT NULL → `product_variants.id` ON DELETE RESTRICT | |
| `sku`, `product_name`, `variant_name` | VARCHAR NOT NULL | **snapshots taken at order time** |
| `quantity` | INTEGER NOT NULL, CHECK > 0 | |
| `unit_price`, `line_total` | NUMERIC(12,2) NOT NULL, CHECK ≥ 0 | |
| `currency` | VARCHAR(3) NOT NULL | |
| `created_at` | TIMESTAMPTZ NOT NULL | |

`UNIQUE(order_id, variant_id)`. Order lines are an **immutable financial record**: they must show
what was bought at the price it was bought for, even after the catalog changes or a product is
deactivated. This denormalization is deliberate and is the opposite of the rule for `cart_items`,
which must always reflect live catalog state. Order rows are never updated after creation.

#### `payments`

| Column | Type | Notes |
| --- | --- | --- |
| `id` | UUID PK | |
| `order_id` | UUID NOT NULL → `orders.id` | indexed |
| `razorpay_payment_id` | VARCHAR(64) NOT NULL UNIQUE | |
| `status` | VARCHAR(24) NOT NULL, CHECK IN (`CREATED`, `AUTHORIZED`, `CAPTURED`, `FAILED`, `REFUNDED`) | |
| `amount` | NUMERIC(12,2) NOT NULL, CHECK ≥ 0 | |
| `amount_minor` | BIGINT NOT NULL, CHECK ≥ 0 | as reported by Razorpay |
| `currency` | VARCHAR(3) NOT NULL | |
| `method` | VARCHAR(32) NULL | |
| `failure_reason` | TEXT NULL | internal only; never rendered raw to a buyer (F§25) |
| `created_at`, `updated_at` | TIMESTAMPTZ NOT NULL | |

Rows here are written **only** by verified webhook processing (ADR-012).

#### `webhook_events`

| Column | Type | Notes |
| --- | --- | --- |
| `id` | UUID PK | |
| `provider` | VARCHAR(24) NOT NULL DEFAULT `'razorpay'` | |
| `event_id` | VARCHAR(128) NOT NULL | Razorpay's event identifier |
| `event_type` | VARCHAR(64) NOT NULL | |
| `signature` | VARCHAR(256) NOT NULL | as received |
| `raw_body` | TEXT NOT NULL | exactly as received, before parsing (P§24) |
| `payload` | JSONB NOT NULL | parsed, after verification |
| `status` | VARCHAR(16) NOT NULL, CHECK IN (`RECEIVED`, `PROCESSED`, `IGNORED`, `FAILED`) | |
| `order_id` | UUID NULL → `orders.id` | nullable: events may arrive before the order is known (P§27) |
| `received_at` | TIMESTAMPTZ NOT NULL | |
| `processed_at` | TIMESTAMPTZ NULL | |

`UNIQUE(provider, event_id)` — the deduplication key that makes at-least-once delivery safe (P§25,
P§26). The uniqueness is enforced by the **database**, not by a read-then-write check, so two
concurrent deliveries of the same event cannot both proceed.

#### `audit_events`

Closes E7. Append-only.

| Column | Type | Notes |
| --- | --- | --- |
| `id` | UUID PK | |
| `seq` | BIGINT GENERATED BY DEFAULT AS IDENTITY, UNIQUE | total order; timestamps can tie |
| `event_type` | VARCHAR(48) NOT NULL, CHECK against the event enum | |
| `actor` | VARCHAR(16) NOT NULL, CHECK IN (`USER`, `AGENT`, `SYSTEM`, `RAZORPAY`) | |
| `session_id`, `cart_id`, `order_id`, `payment_id` | UUID NULL, each FK | nullable — not every event has all four |
| `payload` | JSONB NOT NULL DEFAULT `'{}'` | never contains secrets |
| `created_at` | TIMESTAMPTZ NOT NULL | |

The twelve event types RZP-07 names are mandatory: `CART_CREATED`, `USER_APPROVED`, `POLICY_PASS`,
`POLICY_FAIL`, `ORDER_CREATED`, `RAZORPAY_ORDER_CREATED`, `CHECKOUT_STARTED`,
`PAYMENT_WEBHOOK_RECEIVED`, `PAYMENT_CONFIRMED`, `PAYMENT_FAILED`, `PRICE_CHANGED`,
`INVENTORY_FAILURE`. Four are added because the failure paths would otherwise be unreconstructable:
`APPROVAL_SUPERSEDED`, `APPROVAL_EXPIRED`, `WEBHOOK_SIGNATURE_REJECTED`,
`WEBHOOK_DUPLICATE_IGNORED`.

There is no `updated_at`. The repository exposes `append()` and nothing else, and in a deployed
environment the application's database role is granted `INSERT` and `SELECT` on this table only.

### Concurrency

The Policy Engine's live re-check and the order insert execute in **one transaction**, taking
`SELECT ... FOR UPDATE` on the `inventory` rows involved (closes C6). Without this there is a window
between "inventory verified" and "order created" in which stock can vanish.

## Alternatives considered

**Put approval state on the cart as `approved_at` / `approved_total`.** Rejected: an approval has a
lifecycle of its own — superseded, expired, rejected — and the price-drift scenario requires the
*history* of approvals for a cart, not just its latest state. A superseded approval must remain
readable for audit.

**One `transactions` table instead of separate `orders` and `payments`.** Rejected: P§17 is explicit
that an order and a payment are different things, and a single order can accumulate several payment
attempts.

**Deduplicate webhooks in application code by querying before insert.** Rejected: a read-then-write
check has a race that at-least-once delivery will eventually find. A unique constraint does not.

**Store money as integer paise throughout, avoiding conversion.** Rejected — see ADR-008. D§8 fixes
`NUMERIC(12,2)` for catalog price, and having two different money representations in one schema is
worse than one conversion at one boundary.

**Skip `session_messages` and keep history in a JSONB column.** Rejected: unbounded growth in a row
that is updated on every turn, and no efficient way to read the last N messages.

## Consequences

**Enables.** Every policy rule in P§6 has a table to read from. The price-drift scenario is fully
reconstructable after the fact from `approvals` plus `audit_events`. Duplicate protection and
webhook deduplication are enforced by database constraints rather than by application vigilance.

**Forecloses.** Multi-user accounts, saved carts across devices, refunds and partial fulfilment.
Each is a schema addition, not a redesign.

**Costs.** Eleven tables, one migration, and a set of integrity tests, all before the cart service
can be written. The `orders.approval_id NOT NULL` constraint means test fixtures must construct a
real approval to create an order, which is friction — and it is the friction the constraint exists
to create.

## Implementation implications

- Alembic migration `0003_commerce_schema` in **M6**. Nothing here appears in M1's `0001` or `0002`.
- Models under `backend/app/db/models/`, one module per aggregate.
- Repositories under `backend/app/repositories/`; the audit repository exposes `append()` only.
- The enums are defined once in Python and rendered into `CHECK` constraints by the migration, so
  the application and the database cannot disagree about the legal values.
- **M6 exit tests:** migration applies from zero; every foreign key rejects an orphan; the partial
  unique indexes on `carts` and `approvals` reject a second active cart and a second approval of the
  same cart version; `webhook_events` rejects a duplicate `(provider, event_id)`; an order cannot be
  inserted with a NULL `approval_id`.

## Status

**Accepted, not implemented.** M6. Recorded now because ADR-007, ADR-011, ADR-012, ADR-013 and
ADR-014 all describe behaviour over these tables.
