# Merchant AI Commerce Agent

A conversational commerce agent for a merchant catalog, built on one invariant:

> **LLM proposes → application validates → user authorizes → Razorpay executes → system audits.**

Claude handles natural language and tool selection. PostgreSQL owns product truth. A deterministic
ranking engine owns relevance. A deterministic Policy Engine owns whether money may move. A verified
Razorpay webhook owns whether it did.

The headline demonstration is not the happy path — it is the **price-drift failure**: a buyer
approves a total, the price changes before order creation, the Policy Engine re-fetches live data,
fails, blocks the Razorpay order, and requires fresh approval with a fresh idempotency key.

---

## Current state

| Milestone | Status |
| --- | --- |
| Phase 0 — inspection | Done → [`docs/implementation-status.md`](docs/implementation-status.md) |
| Phase 1 — decisions | Done → [`docs/decisions/`](docs/decisions/) (ADR-001 … ADR-015) |
| **M0 — foundation** | **Done** — app boots, config, migrations infrastructure, logging, tests |
| **M1 — catalog database** | **Done** — 7 catalog tables + compatibility targets, 2 migrations, 32-SKU seed, tests |
| **M2 — catalog read services** | **Done** — repositories, `CatalogService`, `CompatibilityService`, `InventoryService`, canonical target resolution |
| **M3 — ranking engine** | **Done** — hard-constraint filter, four scorers, weight profiles, Top-K, explanations, combinations, cross-sell, `RecommendationService`. The R§10 worked example reproduces exactly. |
| **M4 — LLM layer** | **Done** — Claude client, structured buyer intent, intent extraction across turns, two version-controlled prompts, the eight tool schemas and their argument validation. Every test runs with no API key and no network. |
| M5 … M15 | Not started |

Work stops after M4 by design. The money path is not written before its decisions exist, and M5 —
the agent runtime — is the first milestone that binds a tool to a service. Everything up to here is
verifiable offline: `app/ranking/` is pure, and `app/llm/` depends on a one-method client protocol
rather than on the Anthropic SDK, so no test in this repository calls a live model (ADR-015).

---

## The stack

Fixed by `architecture.md` D§38 and L§44 — PostgreSQL, FastAPI, SQLAlchemy 2, Alembic, psycopg 3,
Pydantic 2, pytest. React arrives at M14. Nothing else is added.

---

## Running it

### Requirements

- Python 3.12 or newer (developed on 3.14)
- Docker, or a PostgreSQL 13+ server you can point `DATABASE_URL` at

PostgreSQL is not optional and is not substitutable. The schema uses `UUID`, `JSONB` and `TEXT[]`,
and [ADR-002](docs/decisions/ADR-002-database-as-product-source-of-truth.md) rules out running the
tests against a different engine — a test that passes on SQLite proves nothing about the database
that ships.

### Setup

```bash
cp .env.example .env          # placeholders only; nothing real is needed for M0/M1

cd backend
python -m venv .venv
.venv/Scripts/activate        # Windows;  source .venv/bin/activate  elsewhere
pip install -e ".[dev]"
```

### Start the database

```bash
docker compose up -d db       # from the repository root
```

This also creates `ai_commerce_test`, the throwaway database the suite uses.

Without Docker, create two databases by hand and point `DATABASE_URL` and `TEST_DATABASE_URL` at
them:

```sql
CREATE USER ai_commerce WITH PASSWORD 'ai_commerce';
CREATE DATABASE ai_commerce      OWNER ai_commerce;
CREATE DATABASE ai_commerce_test OWNER ai_commerce;
```

### Migrate and seed

```bash
cd backend
alembic upgrade head                  # creates the catalog schema from zero
python -m app.seed.circuitcraft       # loads the CircuitCraft catalog (idempotent)
```

Useful variants:

```bash
alembic upgrade head --sql            # render the DDL without connecting to anything
alembic downgrade base                # drop everything the migrations created
python -m app.seed.circuitcraft --validate-only   # check the seed file, touch no database
python -m app.seed.circuitcraft --summary         # what is in the database now
```

### Run the API

```bash
cd backend
uvicorn app.main:app --reload
```

- Health: <http://127.0.0.1:8000/api/health>
- OpenAPI: <http://127.0.0.1:8000/docs>

The application starts without a database on purpose. `/api/health` then answers `503` with
`status: degraded` and tells you the database is unreachable, which is more useful than an import
error.

### Tests

```bash
cd backend
python -m pytest              # everything
python -m pytest -m requires_db   # only the tests that need a live database
```

**Tests that need PostgreSQL skip, loudly, when none is reachable.** They are never silently passed
and never redirected to another engine. If you see

```
SKIPPED [11] No reachable PostgreSQL. Set TEST_DATABASE_URL, or run `docker compose up -d db` ...
```

then the schema, seed and configuration tests ran but the live-database tests did not. Start the
database and run again for a complete result.

What runs without a database: SQLAlchemy metadata assertions, the compiled PostgreSQL DDL, seed-data
integrity, configuration rules, log redaction, the application boot with its health endpoint, and
**the whole ranking engine** — `app/ranking/` takes domain values and returns domain values, so
ADR-004's exit test (the R§10 worked example) is an ordinary unit test — and **the whole LLM
layer**, which is faked at the `LLMClient` protocol rather than at the network.

**Current result: 920 tests, all passing, none skipped** against PostgreSQL 16.4 — 731 of them
without any database at all, and the 198 LLM tests without an API key or a network either.

### Lint and format

```bash
cd backend
python -m ruff check .
python -m ruff format .
```

---

## Layout

```
AI_COMMERCE/
├── architecture.md              the specification — source of truth, never edited
├── artifact-export.md           a derived export of the prior analysis
├── docker-compose.yml           local PostgreSQL 16
├── .env.example                 every setting, placeholders only
│
├── docs/
│   ├── implementation-status.md Phase 0 assessment
│   ├── analysis/                prior analysis of the specification
│   ├── decisions/               ADR-001 … ADR-014
│   └── notes/deviations.md      every departure from the specification, indexed
│
└── backend/
    ├── alembic.ini
    ├── migrations/versions/     0001 catalog, 0002 compatibility targets
    ├── app/
    │   ├── config.py            typed settings; secrets as SecretStr
    │   ├── identifiers.py       deterministic UUIDs for seeded rows
    │   ├── logging_config.py    logging with secret redaction
    │   ├── main.py              FastAPI application factory
    │   ├── db/                  declarative base, session, models
    │   ├── domain/              frozen result types the services return
    │   ├── repositories/        data access; every method is merchant-scoped
    │   ├── attributes.py        one shared meaning for "attribute satisfies expectation"
    │   ├── canonical.py         token normalization and tokenization
    │   ├── services/            catalog, compatibility, inventory (M2), recommendation (M3)
    │   ├── ranking/             filters, scorers, weights, ranker, explain, combinations (M3)
    │   ├── llm/                 client, intent schema, extractor, tool schemas, prompts (M4)
    │   ├── seed/                CircuitCraft catalog and loader
    │   └── api/routes/          health (chat, cart, orders, webhooks arrive later)
    └── tests/
```

---

## Where the decisions live

`architecture.md` is the specification and is **never edited**. Everywhere it leaves something open,
states it two ways, or requires something it never defines, the resolution is an ADR in
[`docs/decisions/`](docs/decisions/README.md).

The ones worth reading first:

| ADR | Why it matters |
| --- | --- |
| [001](docs/decisions/ADR-001-architecture-invariant.md) | The invariant, decomposed into five obligations every later decision is checked against |
| [002](docs/decisions/ADR-002-database-as-product-source-of-truth.md) | Why PostgreSQL, why the variant is the sellable unit, why not SQLite |
| [003](docs/decisions/ADR-003-device-identifier-canonicalization.md) | How "iPhone 16" becomes `iphone_16` without the model guessing |
| [004](docs/decisions/ADR-004-deterministic-recommendation-scoring.md) | The RelevanceScore formula the specification never gives |
| [007](docs/decisions/ADR-007-approval-model.md) | Why the model cannot approve a purchase |
| [008](docs/decisions/ADR-008-money-representation.md) | `Decimal` everywhere, integer paise at exactly one boundary |
| [014](docs/decisions/ADR-014-price-drift-recovery.md) | The flagship failure path, end to end |

---

## Secrets

`.env` is git-ignored; `.env.example` holds placeholders only. `RAZORPAY_KEY_SECRET` and
`RAZORPAY_WEBHOOK_SECRET` never leave the backend — not into a response, not into a log, not into a
prompt. Configuration holds them as `SecretStr`, and the logging pipeline masks both configured
secret values and any field whose name looks like a secret. Both behaviours are tested.

`RAZORPAY_KEY_ID` is public and is meant to reach the browser.

## Contributing rules

1. Never edit `architecture.md`. Record decisions in `docs/decisions/` instead.
2. Never trust model output for a price, SKU, stock level, compatibility claim, approval, or payment
   status. Read it from the database or from a verified webhook.
3. Keep business logic out of route handlers, and database access out of agent code.
4. Tests land with their milestone.
5. Test doubles that imitate Razorpay live only under `backend/tests/fixtures/`, never in
   application code.
