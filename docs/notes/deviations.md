# Deviations from `architecture.md`

`architecture.md` is the source of truth and is never edited. Every place the
implementation resolves an ambiguity in it, adds to it, or departs from its letter is recorded
here with the reason and the ADR that decided it.

This note is **non-authoritative** — it is an index. The ADRs carry the decisions.

Status key: **shipped** = implemented and tested in this session; **decided** = recorded in an ADR,
implemented in a later milestone.

---

## 1. Additions the specification does not contain

| # | Addition | Why | ADR | Status |
| --- | --- | --- | --- | --- |
| A1 | `compatibility_targets` table, in its own migration `0002` | Compatibility is matched by exact string, the model is forbidden from deciding compatibility, and the model is nevertheless what produces that string. Nothing in the specification maps "iPhone 16" onto `iphone_16`, and nothing distinguishes a resolution failure from a genuine no-match. Kept in a separate migration so `0001` remains exactly the specified seven tables. | ADR-003 | shipped |
| A2 | `app/canonical.py` — `normalize_token`, `is_canonical_token` | The deterministic normalization step ADR-003 requires. ADR-003 names `app/services/compatibility_service.py` as its home; it is at the application root instead because the M1 seed validator needs it and `app/services/` does not exist until M2. The M2 service imports it rather than reimplementing it. | ADR-003 | shipped |
| A3 | Composite foreign keys `products(merchant_id, category_id) → categories(merchant_id, id)` and `product_variants(merchant_id, product_id) → products(merchant_id, id)` | D§22's plain foreign keys allow a product to sit in another merchant's category. Merchant scoping is a hard constraint in the recommendation pipeline, so it is enforced by the database rather than by convention. The plain keys D§22 specifies are also present. | ADR-002 | shipped |
| A4 | `UNIQUE(merchants.name)` | Not in D§4. Gives the seed loader a natural key and prevents two CircuitCraft rows. | ADR-002 | shipped |
| A5 | CHECK constraints throughout — canonical-token slugs and identifiers, uppercase SKUs, non-negative money and quantities, `reserved_quantity <= quantity`, JSONB columns restricted to objects, enumerated `rule_type` and `relationship_type` | D§40 principle 9 asks for integrity in the database. Each of these makes a class of bad row unstorable rather than merely discouraged. | ADR-002, ADR-003 | shipped |
| A6 | `UNIQUE` constraints on `compatibility_rules(product_id, target_type, target_identifier, rule_type)` and `product_relationships(source, target, type)` | Prevent duplicate rules and duplicate relationships, which would double-count in ranking and cross-sell. | — | shipped |
| A7 | `ix_product_variants_product_id`, `ix_product_variants_is_active`, `ix_categories_parent_id`, `ix_compatibility_rules_product_id` | Beyond D§24. Loading a product's variants and a product's compatibility rules are the two most common catalog joins; D§24 says indexes should follow real query patterns. | — | shipped |
| A8 | Deterministic UUIDv5 identifiers for seeded rows (`app/identifiers.py`) | Makes seeding idempotent, lets tests name a seeded row, and gives `DEFAULT_MERCHANT_ID` a known value before the database exists. | ADR-002 | shipped |
| A9 | `GET /api/health` | Not in F§26. M0 needs a liveness signal, and it distinguishes "the app is up" from "the catalog is reachable". | ADR-010 | shipped |
| A10 | `session_messages` table | A§38 lists conversation history as session state without giving it a home. An unbounded JSONB column updated on every turn is the wrong shape. | ADR-006 | decided |
| A11 | `approvals`, `idempotency_keys`, `webhook_events`, `sessions` | Required by the Policy Engine, by idempotency and by webhook deduplication; never named as tables in the specification. | ADR-006 | decided |
| A12 | `orders.total_amount_minor`, `payments.amount_minor` | The exact integers exchanged with Razorpay, stored beside the decimals, so the money boundary is auditable after the fact rather than only inside the code path that wrote it. | ADR-008 | decided |
| A13 | `approvals.items_fingerprint` | A total is not a composition: two different carts can reach ₹1,798. `cart_version` catches this in the normal case; the fingerprint catches it unconditionally. | ADR-007 | decided |

## 2. Ambiguities resolved

| # | What the specification leaves open | Resolution | ADR |
| --- | --- | --- | --- |
| R1 | Two ranking weight sets (R§4 vs R§19) | `preference 0.50 / price 0.30 / relevance 0.20`, compatibility as a hard filter. R§4's four-weight set survives as a named `explainability_demo` profile. | ADR-004 |
| R2 | No RelevanceScore formula (R§9) | `0.40 category + 0.30 attribute + 0.20 text + 0.10 tag`, each normalized to `[0,1]`. | ADR-004 |
| R3 | `PriceScore` undefined without a budget | Normalize against the most expensive candidate in the set; `1.0` when the set is degenerate. | ADR-004 |
| R4 | `PreferenceScore` divides by zero | `0.0` when no preferences were stated. | ADR-004 |
| R5 | Top-K scope on multi-product requests | Top 3 **per requested product type**. | ADR-004 |
| R6 | Who writes the recommendation `reason` | The ranking engine, deterministically. The model may paraphrase; the structured field is authoritative. | ADR-004, ADR-010 |
| R7 | `compatibility_rules.constraints` semantics | Predicates evaluated against the **product's own** attributes. | ADR-003 |
| R8 | `rule_type` enum | `compatible` only; `incompatible` and `requires` are reserved but not storable. | ADR-003 |
| R9 | `request_approval` is model-callable, but approval is a human act | The tool may only move state to `WAITING_FOR_APPROVAL` and write a `PENDING` row. Only `POST /api/cart/approve` records `APPROVED`. | ADR-007, ADR-009 |
| R10 | `create_order` is listed as a tool and simultaneously declared off-limits | Not registered as a model-callable tool at all. Order creation is a user-initiated API path behind the Policy Engine. | ADR-009, ADR-011 |
| R11 | Two `/api/chat` response shapes (A§48 vs F§8) | One union contract carrying `session_id`, `message`, `state`, `recommendations[]`, `cart`, `trace[]`, `error`. | ADR-010 |
| R12 | Money units are never reconciled | `Decimal` and `NUMERIC(12,2)` inside; integer minor units only at the Razorpay boundary, converted in one module. | ADR-008 |
| R13 | Approval TTL unspecified | 15 minutes, plus unconditional supersession on any cart change. | ADR-007 |
| R14 | Idempotency key minting, scope and TTL unspecified | Backend-minted at approval, scoped to `(session, cart, cart_version, approved_total, currency)`, 24 hours. | ADR-013 |
| R15 | Spending-limit scope unspecified | Per transaction, from application configuration, one global value. | ADR-011 |
| R16 | Webhook event subscriptions unlisted | `payment.captured`, `payment.failed`, `order.paid`; everything else stored and ignored. | ADR-012 |
| R17 | Tool-call loop limit "an implementation decision" | 8 per user turn. | ADR-009 |
| R18 | Two overlapping state machines (A§25 vs P§30) | Three separate enums — conversation state, approval status, order state — each owned by one table, none derived from another. | ADR-006, ADR-007 |
| R19 | Tool naming: `search_products` vs `search_catalog` | `search_catalog` is canonical. | ADR-009 |
| R20 | Stock disclosure granularity | Coarse `stock_status` in buyer-facing payloads; exact quantities stay internal. | ADR-009, ADR-010 |
| R21 | Build-order conflict (D§36/D§39 vs F§37) | The commerce schema is its own milestone, M6, landing after the read-only agent and before the cart service. | ADR-006 |

## 3. Departures from the letter of the specification

| # | Departure | Reason | ADR |
| --- | --- | --- | --- |
| D1 | A price **decrease** invalidates an approval, exactly as an increase does. P§32 illustrates only an increase. | The buyer approved a specific total; charging a different one, cheaper or not, charges an amount that was never authorized. P§11's rule is stated as inequality. | ADR-014 |
| D2 | `products.category_id` is `NOT NULL`. D§6 does not say. | Category is a hard constraint in the recommendation pipeline; a product with no category could never satisfy it. | ADR-002 |
| D3 | Product colour lives in variant attributes, not product attributes. D§34's example puts `color` on the product. | D§27 says variant attributes are what differentiate sellable versions, and AeroCase Pro has three colours. The example illustrates a single-variant case. | ADR-002 |
| D4 | `compatibility_rules.target_type` is restricted by CHECK to `phone_model`, `laptop_model`, `device`, `device_port`. D§13 describes it as free-form `VARCHAR` with examples. | Same reasoning ADR-003 applies to `rule_type`: a value the compatibility filter cannot interpret is worse than a value that cannot be stored. All four of the specification's own examples are permitted. | ADR-003 |
| D5 | `compatibility_targets.target_type` and `compatibility_rules.target_type` mean different things and are deliberately not the same vocabulary. | The specification uses `phone_model` for cases and `device` for chargers, which are different axes — what the identifier *is* versus how a product *relates* to it. Conflating them would make the specification's own examples inconsistent. | ADR-003 |
| D6 | `ix_products_merchant_id` is created even though `uq_products_merchant_id_slug` already covers the prefix. | D§24 names it explicitly. The redundancy is accepted in favour of following the specified index list. | — |

## 4. Deferred, with the reason

| # | Deferred | Reason | Where |
| --- | --- | --- | --- |
| F1 | `reserved_quantity` lifecycle — nothing reserves, releases or expires | The MVP relies on the Policy Engine's live re-check plus a row lock in one transaction. Reservations would close a narrow race that the lock already covers. | ADR-005, ADR-011 |
| F2 | Variant-level compatibility | The authored catalog does not need it. Would be a nullable `variant_id` on `compatibility_rules` plus an override rule. | ADR-003 |
| F3 | Product images | Neither `products` nor `product_variants` has an image column, and `ProductCard` renders one (F§10). Not added speculatively; a column plus a migration when M14 needs it. | — |
| F4 | Dynamic intent-driven ranking weights | R§12 defers it. Named weight profiles ship instead; the model may select a profile, never emit numbers. | ADR-004 |
| F5 | Refunds and cancellation | `CANCELLED` exists as a state with no transition implemented. | ADR-006 |
| F6 | Multi-currency and conversion | INR only. A mismatch is an error, not something to convert. | ADR-008 |
| F7 | The frontend | F§37 STEP 11 sequences the frontend after the APIs it consumes exist. Nothing is scaffolded at M0. | — |
| F8 | GIN indexes on `products.tags` / `products.attributes` | D§24 says to add them when real query patterns justify them. M2/M3 will show whether they do. | — |

## 5. Still open — needs the project owner

| # | Question | Impact |
| --- | --- | --- |
| U1 | Is `L:\RazorPay\backend` intended to be this project's starting point? It is a separate SQLite-backed FastAPI application outside this working directory. Assumed **no**: SQLite contradicts D§2/D§38, and it is not referenced by any source document. | None on M0/M1. Would change scope if the answer is yes. |
| U2 | The external project brief defining the MUST-WORK / SHOULD-WORK tiers and the "pre-submission gate" (open question F11). `architecture.md` cites it repeatedly and does not contain it. | None on M0/M1. May change priorities from M2 onward. |
| U3 | How PostgreSQL is provisioned on this machine — there is no Docker and no server installed. | The 26 database-backed tests skip until one is available. Everything else is verified. |
