# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A conversational commerce agent for a merchant catalog (CircuitCraft, 32 SKUs), built on one
invariant that every part of the specification restates:

> **LLM proposes → application validates → user authorizes → Razorpay executes → system audits.**

`architecture.md` (16,737 lines, six parts) is the specification. It is **never edited**. Where it
leaves something open, states it two ways, or requires something it never defines, the resolution is
an ADR in `docs/decisions/` — read `docs/decisions/README.md` first, it indexes all fourteen.

**Current state: M0 (foundation) and M1 (catalog database) are complete. M2–M15 are not started.**
The milestone plan is `docs/analysis/02-dependency-map.md`. Build one milestone at a time; the
specification is emphatic (D§39, A§58, F§37) that this must not be built in one pass, and the money
path must not be coded before its decisions exist.

## Commands

Everything runs from `backend/`, using the virtualenv at `backend/.venv`.

```bash
cd backend
pip install -e ".[dev]"

# Database (required — see "PostgreSQL only" below)
docker compose up -d db          # from the repository root; also creates ai_commerce_test
alembic upgrade head
python -m app.seed.circuitcraft            # idempotent
python -m app.seed.circuitcraft --validate-only   # validates the seed file, touches no database
python -m app.seed.circuitcraft --summary         # row counts from the database

alembic upgrade head --sql       # render the whole schema as DDL without connecting
alembic downgrade base

uvicorn app.main:app --reload    # http://127.0.0.1:8000/api/health and /docs

python -m pytest
python -m pytest -m requires_db                        # only the live-database tests
python -m pytest tests/db/test_catalog_schema.py       # one file
python -m pytest -k test_price_round_trips_as_decimal  # one test

python -m ruff check .
python -m ruff format .
```

Tests needing PostgreSQL are marked `requires_db` and **skip with a visible reason** when
`TEST_DATABASE_URL` is unreachable. A run showing skips is an incomplete run, not a pass. Full suite
with a database: **153 tests, all passing**.

## Rules that are not negotiable

These are the ones a well-meaning change is most likely to break.

**`architecture.md` is never edited.** Corrections and resolved ambiguities go to `docs/decisions/`
and are indexed in `docs/notes/deviations.md`.

**PostgreSQL only, in every environment including tests** (ADR-002). The schema depends on `UUID`,
`JSONB` and `TEXT[]`. `Settings` rejects any non-PostgreSQL `DATABASE_URL` outright. Never make a
`requires_db` test pass by pointing it at SQLite — a green run against a different engine proves
nothing. (`L:\RazorPay\backend`, outside this repo, is an unrelated SQLite prototype; do not use it.)

**Money is `Decimal` and `NUMERIC(12,2)`.** No `float` in any arithmetic, Pydantic field, JSON, or
fixture. Seed and API money is a **string** (`"999.00"`) because `json.loads` turns `999.00` into a
float before validation can intervene. Integer minor units exist only inside `app/payments/`,
converted by two functions in one module (ADR-008).

**Deterministic packages must not import `app.llm` or `app.agent`.** `app/services/`, `app/ranking/`,
`app/policy/` and `app/payments/` are the trusted side of the boundary.

**Model output is untrusted input.** A model-supplied `variant_id` or `sku` is a lookup key, never a
fact. No tool accepts a price. `create_order` is deliberately **not registered as a tool at all**
(ADR-009) — order creation is a user-initiated API path behind the Policy Engine.

## Architecture worth knowing before you edit

### Where authority lives

```
Claude → tool call → tool handler → service → repository → PostgreSQL
                                        ↓
                         ranking engine (deterministic, no model)
                                        ↓
                   cart → user approval → Policy Engine → order → Razorpay
                                                                     ↓
                                                    verified webhook → payment truth
```

PostgreSQL owns product facts. The ranking engine owns relevance. The Policy Engine owns whether
money may move. A verified Razorpay webhook owns whether it did. The model owns none of these.

### Three state machines that share value names

A recurring trap: `APPROVED`, `POLICY_VALIDATED` and `PAYMENT_CONFIRMED` appear in more than one
enum in the source document. They are kept as three separate enums, each owned by one table, and
**none is ever derived from another** (ADR-006, ADR-007):

| Enum | Owner | Read by |
| --- | --- | --- |
| Conversation state | `sessions.conversation_state` | the UI and the agent runtime |
| Approval status | `approvals.status` | the Policy Engine |
| Order state | `orders.status` | the Policy Engine, the webhook handler, the UI |

A session whose conversation state says `APPROVED` authorizes nothing. Only an `approvals` row does.

### Compatibility resolution (ADR-003) — the subtlest part of the catalog

The specification forbids the model from deciding compatibility, yet the model is what produces the
identifier string that gets matched. The pipeline closes that gap:

```
user text → [LLM] a phrase ("iPhone 16") → normalize_token() → resolve against
compatibility_targets → canonical id ("iphone_16") → query compatibility_rules
```

- `app/canonical.py` holds `normalize_token`. It handles case and punctuation only:
  `normalize_token("iphone16")` is `"iphone16"`, **not** `"iphone_16"`. That is precisely why
  `compatibility_targets.aliases` exists.
- `compatibility_targets.target_type` and `compatibility_rules.target_type` **mean different
  things**. The first classifies what the identifier *is* (`phone_model`, `laptop_model`,
  `device_port`); the second classifies how a product *relates* to it, and adds the broader `device`
  the specification uses for chargers. A query for "compatible with the phone `iphone_16`" matches
  rules whose `target_type` is in `('phone_model', 'device')`.
- Unresolvable, or ambiguous, means **ask the buyer**. Never guess, never fall back to substring
  matching, never drop the compatibility constraint to obtain results.
- `compatibility_rules.constraints` are predicates on the **product's own attributes**:
  `{"minimum_wattage": 20, "fast_charge": true}` means "provided this product supplies ≥20W and
  supports fast charging".

### The variant is the sellable unit

SKU, price, currency and stock live on `product_variants` / `inventory`, never on `products`. A
product is "what is this"; a variant is "which exact sellable version". Search returns one row per
variant.

### Hard constraints eliminate, they never score

Merchant, activity, category, budget, compatibility, required specification and inventory are
**filters applied before ranking** (ADR-005). There is no weight configuration in which a cheap
incompatible product can outrank a compatible one. Ranking weights and formulas are in ADR-004; the
engine is deterministic and the model never computes a score or writes a recommendation `reason`.

## Working on the schema and migrations

**Alembic applies the metadata naming convention on top of names you pass.** `CheckConstraint` in a
migration must therefore take the **bare** name (`"price_is_not_negative"`), not the prefixed one, or
you get `ck_products_ck_products_...`. Primary keys, unique constraints and foreign keys take their
full names.

**`tests/db/test_migrations.py` diffs the rendered migration DDL against the compiled model
metadata**, constraint names included. Change a model without mirroring it in a migration and that
test fails. It runs without a database, so there is no excuse for drift.

**Composite merchant-scoping foreign keys create ambiguous relationships.** `products` has two FK
paths to `categories` (the plain `category_id` key plus the composite merchant-scoping key), so ORM
relationships across those pairs need an explicit `foreign_keys=`. SQLAlchemy configures mappers
lazily, so the error only appears when something queries; `test_every_orm_relationship_resolves`
forces configuration to catch it offline.

**Migration `0001` is exactly the seven tables the specification defines.** `compatibility_targets`
is in `0002` on purpose, so the specified schema stays auditable on its own. A test enforces the
split. Commerce tables (ADR-006) belong to M6 and must not appear before then — a test enforces that
too.

**Seeded rows have deterministic UUIDv5 identifiers** (`app/identifiers.py`), which is what makes
seeding idempotent and lets tests name a row without querying for it. `DEFAULT_MERCHANT_ID` is
derived the same way, so merchant scoping is configuration rather than discovery.

**Seed data is authored under a claims rule**: fictional CircuitCraft own-brand items described only
by structural attributes (material, colour, wattage, port type, length, capacity, battery hours,
ANC). No certifications, ratings, review counts, test results, warranty terms, or real third-party
brand names. Values the specification does supply are reproduced verbatim.

The catalog is deliberately shaped so each filter is separately testable: an out-of-stock variant, an
iPhone 15 case that must be excluded from iPhone 16 searches, products either side of the ₹1,500
line, earbuds with no compatibility rules, and `pixel_9` as a *resolvable* device with zero
compatible products — the no-match path as distinct from an unresolved device.

## Payments, when you get there

Not implemented. Read ADR-011 through ADR-014 before writing any of it.

- The Policy Engine re-reads price and stock **live, inside the order transaction**, never from
  `cart_items.unit_price_snapshot`. It evaluates all ten rules rather than stopping at the first
  failure, and returns machine-readable reason codes.
- The internal order is committed **before** Razorpay is called.
- Webhook verification runs against the **raw request body**, captured before parsing — so that
  route must not bind a Pydantic body model. Deduplication is a `UNIQUE` constraint, not a
  read-then-write check.
- A price change in **either direction** invalidates an approval and requires reconfirmation with a
  fresh idempotency key. Price drift, out-of-stock, policy failure and payment failure all recover
  through the same path.
- Razorpay test doubles live only under `backend/tests/fixtures/`, never in application code.

## Where the decisions are

| Question | Read |
| --- | --- |
| Why is it built this way at all? | `docs/decisions/ADR-001-architecture-invariant.md` |
| What was the repo like before, and how was it verified? | `docs/implementation-status.md` |
| Where does this depart from the specification, and why? | `docs/notes/deviations.md` |
| What is the build order? | `docs/analysis/02-dependency-map.md` |
| What did the specification leave open? | `docs/analysis/03-open-questions.md` |
