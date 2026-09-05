# Day 01 — 30 August 2026

**Date:** 30 August 2026 (work continues past midnight into 31 August)
**Time:** 22:19 – 00:17 IST (+0530), from commit timestamps `621e5cb` … `835d321`

## What Was I Trying to Do?

Get from "here is a 16,737-line specification" to "there is a database with real products in
it and code that can read them". Nothing about the agent, nothing about payments. Just the
foundation: config, migrations, a seeded catalog, and the read layer on top of it.

The specification is `architecture.md`. It came into the repo in the first commit along with
prior analysis of it (`docs/analysis/`), and the rule from the start was that it is never
edited — where it is ambiguous, the resolution goes in an ADR instead.

## Question

Where does product truth live, and how do I stop anything else from claiming to own it?

## Answer

PostgreSQL. The seven catalog tables the specification defines went in first as migration
`0001`, and everything above them reads through repositories and services. The seed file is
validated as *data* before it is allowed near the database.

## Why?

The whole project rests on one invariant — the model proposes, the application validates.
That is only true if there is one place a price can come from. Putting the schema and the
seed in before anything that could generate product text was deliberate: by the time an LLM
exists in this codebase, there is already a table it has to defer to.

The seed being a separate, independently validated file matters for the same reason. A
malformed catalog fails with a message naming the offending row rather than as a constraint
violation halfway through a transaction, and on a machine with no PostgreSQL the catalog is
still checked (`backend/app/seed/schema.py`, `f0bdf8b`).

## What Changed?

- Repository initialised with `architecture.md` and the prior analysis (`621e5cb`)
- A written assessment of what already existed and what did not (`2d5b1e2`)
- Fourteen ADRs, written before the code they govern (`641b5e3`) — ADR-001 through ADR-014
- M0 foundation: `Settings`, logging with secret redaction, Alembic, health endpoint,
  `docker-compose.yml`, the test harness (`16ad85d`)
- M1 schema: nine ORM models and migrations `0001_catalog_schema` and
  `0002_compatibility_targets` (`423c09a`)
- M1 seed: `app/seed/circuitcraft.py`, `app/seed/schema.py`, `catalog.json`, `app/canonical.py`
  (`8355d2a`)
- M1 tests: catalog integrity, schema, migration-vs-model diff, seed validation (`f0bdf8b`)
- `CLAUDE.md` — the standing engineering rules for this repository (`1191b64`)
- M2: domain types and repositories (`9e475c3`), then catalog, compatibility and inventory
  read services (`6a1e352`), then their tests (`835d321`)

Migration `0001` is exactly the seven tables the specification defines. `compatibility_targets`
is in `0002` on purpose, so the specified schema stays auditable on its own.

## Problem I Hit

Two defects that only appeared once a real database was involved (`bca07c8`).

The first: `Category.products` was ambiguous. `products` has two foreign-key paths to
`categories` — the plain `category_id` and the composite merchant-scoping key — and SQLAlchemy
configures mappers lazily, so nothing had triggered the failure until something queried.

The second was smaller: a raw-SQL constraint test expected the violation at flush time.
PostgreSQL raises it at execute time. The constraint was working; the assertion was in the
wrong place.

See `docs/bugs/ambiguous-orm-category-foreign-keys.md` (BUG-011).

## What I Tried

For the mapper problem, the fix was an explicit `foreign_keys=` on the relationship. The part
worth keeping was the follow-up: a test that calls `configure_mappers()` so this class of error
is caught **offline**, without a database, instead of waiting for a query to trigger it
(`test_every_orm_relationship_resolves` in `backend/tests/db/test_catalog_schema.py`).

## What Worked

The migrations apply from zero and roll back to base. The seed loads and is idempotent — a
second run changes nothing, because every row's primary key is a UUIDv5 derived from its
natural key (`app/identifiers.py`).

M0 and M1 verified: **153 tests pass, 0 fail, 0 skip** (`docs/implementation-status.md` §11).
Of those, 127 need no database.

## What Did Not Work?

This machine has neither Docker nor an installed PostgreSQL. Rather than report "migrations run"
as unproven, a throwaway PostgreSQL 16.4 was unpacked from the official Windows binary archive
into a temporary directory — `initdb` plus `pg_ctl` in user space, no installer, no service.
That is documented as the workaround it is (`docs/implementation-status.md` §11), not as a
solution.

## Decision

**The database owns product facts, and the specification is never edited.** Ambiguities are
resolved in ADRs and indexed in `docs/notes/deviations.md`.

Fourteen ADRs were written before the code. The ones that shaped this day: ADR-002 (PostgreSQL
only, in every environment including tests), ADR-003 (device identifier canonicalization),
ADR-008 (money is `Decimal` and `NUMERIC(12,2)`; a JSON money value is a **string**, because
`json.loads` turns `999.00` into a float before validation can intervene).

## Testing

```
python -m pytest                 # 153 passed, 0 failed, 0 skipped
alembic upgrade head             # applies from zero
alembic downgrade base           # rolls back cleanly
python -m app.seed.circuitcraft  # idempotent; second run changes nothing
```

`tests/db/test_migrations.py` diffs the rendered migration DDL against the compiled model
metadata, constraint names included, and runs without a database — so a model change that is
not mirrored in a migration fails offline.

## Result

A seeded catalog in PostgreSQL, read services over it, and a test suite that proves the schema
and the seed agree. No agent, no LLM, no cart, no money.

## What I Learned

Lazy mapper configuration hides relationship errors until something queries. If a class of
error can only appear at runtime, write the test that forces it to appear at import time.

Validating the seed as data — separately from loading it — pays for itself the first time a
row is wrong.

## Remaining Work

- Ranking engine (M3)
- LLM layer (M4)
- Everything above it

## Evidence

| Kind | Reference |
| --- | --- |
| Commits | `621e5cb`, `2d5b1e2`, `641b5e3`, `16ad85d`, `423c09a`, `8355d2a`, `f0bdf8b`, `bca07c8`, `1191b64`, `88306be`, `36368ad`, `9e475c3`, `6a1e352`, `835d321` |
| Migrations | `0001_catalog_schema.py`, `0002_compatibility_targets.py` |
| Tests | `tests/db/test_catalog_integrity.py`, `tests/db/test_catalog_schema.py`, `tests/db/test_migrations.py`, `tests/seed/test_catalog_seed.py` |
| Docs | `docs/implementation-status.md` §11, `docs/decisions/ADR-001` … `ADR-014` |
| Bug report | `docs/bugs/ambiguous-orm-category-foreign-keys.md` (BUG-011) |
