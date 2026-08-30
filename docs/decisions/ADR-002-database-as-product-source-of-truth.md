# ADR-002: PostgreSQL as the Source of Truth for Product Facts

**Status:** Accepted (2026-08-30)
**Milestone:** M1 (implemented), binding on M2 onward
**Source references:** `architecture.md` D§1, D§2, D§35, D§37–D§41, R§17 (RULE 2, 6, 7), L§12, L§13, A§55
**Related open questions:** B8 (merchant scoping), B9 (currency), F12 (seed catalog)

## Context

D§1 states that PostgreSQL is "the authoritative source of truth for merchant catalog and commerce
data" and enumerates what it must contain: merchant, product, category, SKU, price, currency,
product attributes, variants, inventory, compatibility, product relationships and tags. D§35 draws
the line the other way — the database "does NOT decide 'this is the best product'"; it supplies
facts, and other layers decide.

D§38 fixes the stack: PostgreSQL, FastAPI, SQLAlchemy, Alembic, a psycopg-family driver, Pydantic.
D§39 fixes the first implementation task: the seven Phase-1 catalog tables, their constraints, their
indexes, an Alembic migration, seed data and database tests — and nothing else.

L§12 adds the subtlety that matters most in practice: Claude's general world knowledge is not the
merchant catalog. Claude may know an iPhone 16 exists; that tells it nothing about which CircuitCraft
cases fit one.

## Problem

Three questions have to be settled before the first table is created. What exactly is "product
truth" and where does each fact live? What is the authoritative unit of sale? And how does a fact
get from the database to the model without the model becoming a co-author of it?

## Decision

**PostgreSQL is the single authoritative store for catalog facts.** SQLAlchemy 2.x is the ORM,
Alembic owns schema evolution, and no other database engine is used — in particular, **SQLite is not
an acceptable substitute in any environment, including tests**, because the schema depends on
`UUID`, `JSONB` and `TEXT[]` and because a test that passes on a different engine proves nothing
about the engine that runs in production.

**The variant is the sellable unit.** SKU, price, currency and inventory belong to
`product_variants` and `inventory`, never to `products` (D§8, D§10, D§11, D§12). A product is "what
is this"; a variant is "which exact sellable version". A product with a single variant is normal and
expected (D§9).

**Facts have exactly one home.**

| Fact | Authoritative location |
| --- | --- |
| Product identity, description, brand, tags | `products` |
| Category membership | `products.category_id` → `categories` |
| SKU | `product_variants.sku` |
| Price, currency | `product_variants.price`, `product_variants.currency` |
| Stock | `inventory.quantity`, `inventory.reserved_quantity` |
| Compatibility | `compatibility_rules` (never inferred from attributes) |
| Cross-sell / bundle | `product_relationships` |
| Industry-specific characteristics | `products.attributes`, `product_variants.attributes` (JSONB) |

**Structured stays structured.** D§7 is binding: merchant, category, product identity, SKU, price,
inventory and compatibility MUST remain first-class columns. JSONB carries only industry-variable
characteristics. A price hidden inside `attributes` is a defect, not a shortcut.

**Attributes are not compatibility.** D§28 is binding. "This charger is 65W" is an attribute; "this
charger works with a MacBook Air M3" is a compatibility rule. Compatibility is never derived from
attributes by the application, and never asserted by the model.

**Merchant scoping is resolved server-side.** The schema is multi-merchant. For the MVP a single
configured `DEFAULT_MERCHANT_ID` is resolved in the API/config layer and injected into every service
call. A merchant identifier MUST NOT be read from model output or from a client request body
(closes B8).

**Single currency for the MVP.** INR only. Currency is stored explicitly on both `merchants` and
`product_variants` and is never assumed. No conversion is implemented; a currency mismatch is an
error, not something to convert (closes B9). See ADR-008.

**The model reads the catalog only through tools.** There is no path from Claude to SQL. The chain
is Claude → tool call → tool handler → service → repository → SQLAlchemy → PostgreSQL, and results
return along the same chain, narrowed and validated (L§11, A§20).

**Seed data is authored, and authored under a claims rule.** `architecture.md` cites a 30–36 SKU
CircuitCraft catalog but supplies only one complete record. The catalog is therefore authored as a
deliverable of M1. Every value the specification does give is reproduced exactly. Everything else is
a fictional CircuitCraft own-brand item described only by structural attributes — material, colour,
wattage, port type, length, capacity, battery hours, ANC yes/no. No certifications, ratings, review
counts, test results, warranty terms, or real third-party brand names appear in the seed
(closes F12).

## Alternatives considered

**SQLite for local development and tests, PostgreSQL in production.** Tempting on a machine with no
Postgres and no Docker — which is exactly this machine. Rejected: `JSONB`, `TEXT[]`, `gen_random_uuid()`
and PostgreSQL's constraint semantics have no faithful SQLite equivalent, so the tests would be
testing a different schema than the one that ships. An adjacent prototype on this drive
(`L:\RazorPay\backend`) took this path and is a live example of the divergence. Instead, the schema
is verified by compiling the real PostgreSQL DDL and asserting against SQLAlchemy metadata, and the
live-database tests skip loudly rather than silently passing against a weaker engine.

**Product-level price and stock, with variants added later.** Simpler for a 30-SKU catalog.
Rejected: D§9 and D§12 are explicit, and retrofitting the sellable unit after the cart, order and
policy layers are built would touch every one of them.

**A document store for the whole catalog, since attributes are already JSONB.** Rejected: D§2 lists
foreign-key integrity, transactions and reliable price/inventory state as the reasons PostgreSQL was
chosen. Those are the properties the money path depends on.

**Denormalising cross-sell as `products.cross_sell_product_id`.** Explicitly rejected by D§17,
because one product has many related products.

## Consequences

**Enables.** Deterministic, reproducible catalog queries; referential integrity enforced by the
database rather than by application discipline; a schema that supports other merchant industries
without migration, because industry variance lives in JSONB.

**Forecloses.** Any environment where the application runs without PostgreSQL. On a developer
machine with neither Docker nor a local server, the database-backed tests cannot run at all — they
skip. That is a deliberate trade of convenience for honesty.

**Costs.** A container (or a local server) is required to run the full suite. Compatibility must be
authored as explicit rows rather than inferred, which makes seeding more work and makes the results
correct.

## Implementation implications

- Seven Phase-1 tables, exactly as specified in D§4–D§16, in Alembic migration `0001`.
- UUID primary keys everywhere; SKU is never a primary key (D§21).
- `UNIQUE(merchant_id, slug)` on `categories` and `products`; `UNIQUE(merchant_id, sku)` on
  `product_variants`; `UNIQUE(variant_id)` on `inventory` (D§23).
- Indexes exactly as D§24 specifies. GIN indexes on `products.tags` / `products.attributes` are
  **not** created in M1 — D§24 says to add them only when real query patterns justify them.
- All timestamps `TIMESTAMPTZ`. Money `NUMERIC(12,2)` (see ADR-008). Attributes `JSONB` constrained
  to JSON objects. Tags `TEXT[]`.
- `DEFAULT_MERCHANT_ID` is a typed configuration value, read once at the API boundary.
- Seed data lives in `backend/app/seed/data/catalog.json` with a loader in
  `backend/app/seed/circuitcraft.py`. Loading MUST be idempotent — re-running it re-uses existing
  rows rather than duplicating them.
- Tests assert schema integrity from metadata and compiled DDL, and assert seed integrity as data
  (SKU uniqueness, slug format, referential closure, `Decimal` money).

## Status

**Accepted.** Implemented in M1 for the catalog. The commerce half of "commerce data" is designed in
ADR-006 and implemented in M6.
