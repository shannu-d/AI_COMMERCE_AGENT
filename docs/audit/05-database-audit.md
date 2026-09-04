# 05 — Database Audit

**Engine:** PostgreSQL 16 on `127.0.0.1:5432`, database `ai_commerce` (with `ai_commerce_test`
alongside). PostgreSQL was **available** during this audit, so everything below is read from the live
database rather than inferred from the models.

## Live schema

| Metric | Count |
| --- | --- |
| Tables | **20** |
| Primary keys | 20 |
| Foreign keys | **36** |
| Unique constraints | 19 |
| Check constraints | **56** |
| Indexes | 57 |

Fifty-six CHECK constraints across twenty tables is unusually dense, and it is what makes the three
state machines enforceable in the database rather than only in Python.

## Tables and live row counts (after this audit's end-to-end run)

| Table | Rows | Note |
| --- | --- | --- |
| `merchants` | 1 | CircuitCraft |
| `categories` | 10 | slugs `phone_case`, `charger`, `usb_cable`, `earbuds`, and others |
| `products` | 21 | |
| `product_variants` | 32 | the sellable unit |
| `inventory` | 32 | one row per variant |
| `compatibility_targets` | 7 | ADR-003 canonical ids and aliases |
| `compatibility_rules` | 21 | |
| `product_relationships` | 12 | upsell and accessory links |
| `sessions` | 4 | |
| `session_messages` | 7 | server-owned conversation history |
| `carts` | 2 | |
| `cart_items` | 2 | |
| `approvals` | 2 | one `APPROVED`, one `SUPERSEDED` |
| `idempotency_keys` | 2 | |
| `orders` | **1** | **the first order ever created in this project — by this audit** |
| `order_items` | 1 | |
| `payments` | 0 | blocked together with M11 |
| `webhook_events` | 2 | one from an earlier tunnel test, one from this audit |
| `audit_events` | 13 | the full trail |
| `alembic_version` | 1 | at head |

## Money columns

All twelve business money columns are `NUMERIC(12,2)`, verified by an `information_schema` query:
`approvals.approved_total`, `cart_items.unit_price_snapshot`, `cart_items.line_total`,
`carts.subtotal_amount`, `carts.total_amount`, `idempotency_keys.approved_total`,
`order_items.unit_price`, `order_items.line_total`, `orders.subtotal_amount`, `orders.total_amount`,
`payments.amount`, `product_variants.price`.

Two further columns are `BIGINT`: `orders.total_amount_minor` and `payments.amount_minor`. **This is
correct, not a defect.** ADR-008 requires integer minor units at the provider boundary, converted in
exactly one module. The live conversion was confirmed during the end-to-end run: `999.00` became
`99900`.

## Migrations

Four, and the split is deliberate.

| Migration | Contents |
| --- | --- |
| `0001_catalog_schema` | Exactly the seven tables the specification defines |
| `0002_compatibility_targets` | ADR-003's resolution table, kept separate so the specified schema stays auditable on its own |
| `0003_sessions` | `sessions` and `session_messages`, which arrived in M5 (deviation A28) |
| `0004_commerce_schema` | ADR-006's remaining nine commerce tables |

**Model to migration consistency** is enforced offline by `tests/db/test_migrations.py`, which diffs
the rendered migration DDL against the compiled model metadata, constraint names included. It needs
no database, so drift cannot hide behind an unavailable environment.

**Migration round-trip** (empty to head to base to head) is proven by
`tests/db/test_catalog_integrity.py`, which downgrades to base at its own teardown. All 88 database
tests passed with zero skips.

**Audit decision — a destructive test deliberately not run.** This audit did **not** execute
`alembic downgrade base` against the primary `ai_commerce` database. Doing so would have destroyed
the live evidence this report depends on — the order, the approvals and the audit trail. The
round-trip is already proven by the suite against `ai_commerce_test`, so repeating it destructively
would have added no information and removed a great deal.

## Seed

`python -m app.seed.circuitcraft` is idempotent. Seeded rows carry deterministic UUIDv5 identifiers
(`app/identifiers.py`), so re-seeding updates rather than duplicates, and tests can name a row
without querying for it. Thirty-two seed tests pass. Live counts confirm a correct seed: 21 products,
32 variants, 32 inventory rows.

The catalogue is deliberately shaped so that each filter is separately testable: an out-of-stock
variant, an iPhone 15 case that must be excluded from iPhone 16 searches, products on either side of
the ₹1,500 line, earbuds with no compatibility rules, and `pixel_9` as a *resolvable* device with
zero compatible products — which distinguishes the no-match path from an unresolved device.

## Relationships

`products` has two foreign-key paths to `categories` (the plain `category_id` plus the composite
merchant-scoping key), which makes ORM relationships across those pairs ambiguous without an explicit
`foreign_keys=`. SQLAlchemy configures mappers lazily, so the error would otherwise appear only when
something queried; `test_every_orm_relationship_resolves` forces configuration offline to catch it.

## Verdict

**FULL.** The database layer is the most thoroughly verified part of this system. No defects were
found at any level — schema, constraints, migrations, seed or relationships.
