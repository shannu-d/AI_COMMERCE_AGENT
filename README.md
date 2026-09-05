# EASY BUY — an AI commerce agent, built on Razorpay

A conversational commerce agent for a merchant catalog, built on one invariant:

> **LLM proposes → application validates → user authorizes → Razorpay executes → verified webhook confirms → system audits.**

Groq (`openai/gpt-oss-120b`, locked — ADR-018) handles natural language and tool selection.
PostgreSQL owns product truth. A deterministic ranking engine owns relevance. A deterministic
Policy Engine owns whether money may move. A verified Razorpay webhook owns whether it did.

**Razorpay Buildathon, Track 1 (AI Growth & Agentic Commerce):** see
[`docs/SUBMISSION.md`](docs/SUBMISSION.md) for how this meets the brief, and
[`docs/DEMO-SCRIPT.md`](docs/DEMO-SCRIPT.md) for the walkthrough. Two ways to buy from this
merchant:

1. **A human, through the AI agent** — chat → grounded recommendations → cart → explicit
   approval → real Razorpay Checkout → signed webhook → confirmed order.
2. **An external AI buyer, over MCP** (`app/mcp/`, ADR-024) — `search_catalog` →
   `create_quote` → `authorize_and_pay` (a mandate that must name the exact amount) →
   `get_order_status`.

The headline failure demo is the **price-drift scenario**: a buyer approves a total, the price
changes before order creation, the Policy Engine re-fetches live data, fails, blocks the Razorpay
order, and requires fresh approval with a fresh idempotency key.

---

## Current state

**Canonical current state lives in [`docs/PROJECT_STATE.md`](docs/PROJECT_STATE.md)** — read that
before this table if the two ever disagree. In summary, as of 2026-09-05:

| Area | Status |
| --- | --- |
| Catalog, ranking, LLM layer, agent runtime (M0–M5) | ✅ Complete |
| Cart, approval, Policy Engine, orders + idempotency (M6–M10) | ✅ Complete |
| **Razorpay orders + webhook (M11–M12)** | ✅ **Complete, live-verified** — a real test-mode payment completed end to end |
| Audit log (M13) | ✅ Complete |
| Frontend — chat, cart, checkout, order status, merchant dashboard (M14, M16) | ✅ Complete |
| Authentication — customers + merchants (ADR-023) | ✅ Complete |
| **MCP server for external AI buyers (ADR-024)** | ✅ Complete, live-verified |
| Integration & evaluation (M15) | ✅ Backend scenarios **and a 270-case commerce evaluation suite** (`backend/tests/evals/`, 3,470 deterministic checks) — see [`docs/EVALUATION-REPORT.md`](docs/EVALUATION-REPORT.md) |

Backend: **1,711 passing + 2 xfailed, 0 skipped**, against a real PostgreSQL. The two xfails
are finding F-1, recorded as strict expected failures so the defect stays visible and a fix
cannot land silently. Frontend: **71 passing**, typecheck/eslint/build clean.

> **LLM provider: Groq, locked (ADR-018).** `architecture.md` names Claude Sonnet; that is
> superseded by direct owner decision and is documented in `docs/decisions/ADR-018-...md`.

---

## The stack

PostgreSQL, FastAPI, SQLAlchemy 2, Alembic, psycopg 3, Pydantic 2, pytest (backend); Vite, React
18, TypeScript, Assistant-UI, TanStack Query, Zod (frontend); Groq (LLM); Razorpay test mode
(payments); MCP / FastMCP (the AI-buyer surface).

---

## Running it

Full instructions, including the Razorpay dashboard webhook setup and test-payment instruments,
are in **[`docs/RUNBOOK.md`](docs/RUNBOOK.md)**. Short version:

```bash
# database
docker compose up -d db                       # from the repository root
cd backend
pip install -e ".[dev]"
alembic upgrade head
python -m app.seed.circuitcraft               # 200 products / 360 SKUs, idempotent
python -m app.admin.provision_merchant --email owner@easybuy.test   # a merchant login

# backend  (port 8000 may be taken by something else on your machine — use 8004)
uvicorn app.main:app --host 127.0.0.1 --port 8004

# frontend
cd frontend && npm install
echo "VITE_API_BASE_URL=http://127.0.0.1:8004" > .env
npm run dev -- --host 127.0.0.1 --port 5173

# the MCP server, for an external AI buyer
cd backend && python -m app.mcp               # streamable-HTTP on :8005, or --stdio

# a public tunnel, for Razorpay's webhook
ngrok http 8004
```

PostgreSQL is not optional and not substitutable — the schema uses `UUID`, `JSONB` and `TEXT[]`,
and [ADR-002](docs/decisions/ADR-002-database-as-product-source-of-truth.md) rules out testing
against a different engine.

### Tests

```bash
cd backend
TEST_DATABASE_URL="postgresql+psycopg://ai_commerce:ai_commerce@127.0.0.1:5432/ai_commerce_test" \
  python -m pytest -q                          # 1711 passed, 2 xfailed, 0 skipped
python -m ruff check . && python -m ruff format --check .

cd ../frontend
npm run test && npx tsc -b --noEmit && npx eslint . --max-warnings 0 && npm run build
```

Use `127.0.0.1`, not `localhost`, for `TEST_DATABASE_URL` — a throwaway PostgreSQL binds IPv4-only
and `localhost` resolves to `::1` first, silently skipping the whole `requires_db` suite. Tests
that need PostgreSQL skip **loudly**, never redirect to another engine, and never pass silently.

What runs with no database, no API key and no network at all: SQLAlchemy metadata assertions, the
compiled PostgreSQL DDL, seed-data integrity, configuration rules, log redaction, the application
boot, the whole ranking engine (pure — ADR-004's R§10 worked example is an ordinary unit test), and
the whole LLM layer (faked at the `LLMClient` protocol — ADR-015).

---

## Layout

```
AI_COMMERCE/
├── architecture.md              the specification — source of truth, never edited
├── docker-compose.yml           local PostgreSQL 16
├── .env.example                 every setting, placeholders only
│
├── docs/
│   ├── SUBMISSION.md             the Razorpay Buildathon Track 1 write-up
│   ├── RUNBOOK.md                exact commands to bring every service up
│   ├── DEMO-SCRIPT.md            the video walkthrough
│   ├── PROJECT_STATE.md          canonical current state — wins over every other doc
│   ├── implementation-status.md  the full build narrative, milestone by milestone
│   ├── decisions/                ADR-001 … ADR-024, indexed in README.md
│   └── notes/
│       ├── deviations.md               every departure from the specification
│       └── bugs-found-during-development.md
│
├── backend/
│   ├── alembic.ini
│   ├── migrations/versions/     0001 catalog … 0006 merchant activity
│   ├── app/
│   │   ├── config.py            typed settings; secrets as SecretStr
│   │   ├── main.py              FastAPI application factory
│   │   ├── db/                  declarative base, session, models
│   │   ├── domain/               frozen result types the services return
│   │   ├── repositories/        data access; every method is merchant-scoped
│   │   ├── services/            catalog, compatibility, inventory, recommendation, cart,
│   │   │                        approval, order, webhook, audit, auth, merchant
│   │   ├── ranking/              deterministic scoring — no model, no I/O
│   │   ├── llm/                 the Groq client, intent schema, tool schemas, prompts
│   │   ├── agent/                the tool loop that binds llm/ to services/
│   │   ├── policy/               the Policy Engine — pure, ten rules
│   │   ├── payments/             Razorpay client + money conversion — the only provider door
│   │   ├── mcp/                  the MCP server for external AI buyers (ADR-024)
│   │   ├── admin/                operator commands (provisioning a merchant login)
│   │   ├── seed/                 the EASY BUY catalog (360 SKUs) and loader
│   │   └── api/routes/           health, auth, account, catalog, chat, sessions, cart,
│   │                              orders, webhooks, merchant
│   └── tests/                    mirrors app/, plus integration/ and mcp/
│
└── frontend/
    └── src/
        ├── api/                  the one place responses are parsed (Zod) and requests sent
        ├── auth/                 token storage, boot call, route guards
        ├── features/             chat, agent recommendations, cart, checkout, merchant
        ├── pages/                routed screens, incl. merchant/*
        └── layout/               the shared shell and navigation
```

---

## Where the decisions live

`architecture.md` is the specification and is **never edited**. Everywhere it leaves something
open, states it two ways, or requires something it never defines, the resolution is an ADR in
[`docs/decisions/`](docs/decisions/README.md) (24 of them, append-only).

The ones worth reading first:

| ADR | Why it matters |
| --- | --- |
| [001](docs/decisions/ADR-001-architecture-invariant.md) | The invariant, decomposed into five obligations every later decision is checked against |
| [002](docs/decisions/ADR-002-database-as-product-source-of-truth.md) | Why PostgreSQL, why the variant is the sellable unit |
| [004](docs/decisions/ADR-004-deterministic-recommendation-scoring.md) | The RelevanceScore formula the specification never gives |
| [008](docs/decisions/ADR-008-money-representation.md) | `Decimal` everywhere, integer paise at exactly one boundary |
| [011](docs/decisions/ADR-011-razorpay-order-creation-boundary.md) | The one path to a Razorpay order, and why `create_order` is not a tool |
| [012](docs/decisions/ADR-012-webhook-as-payment-truth.md) | Why a signed webhook, and nothing else, marks an order paid |
| [014](docs/decisions/ADR-014-price-drift-recovery.md) | The flagship failure path, end to end |
| [018](docs/decisions/ADR-018-groq-as-the-locked-llm-provider.md) | Groq is the locked provider — permanent, by owner decision |
| [023](docs/decisions/ADR-023-authentication-and-authorization.md) | Customers and merchants, opaque bearer tokens, ownership through the session |
| [024](docs/decisions/ADR-024-mcp-surface-for-ai-buyers.md) | How an external AI buyer authorises a specific amount and pays |

---

## Secrets

`.env` is git-ignored; `.env.example` holds placeholders only. `GROQ_API_KEY`,
`RAZORPAY_KEY_SECRET` and `RAZORPAY_WEBHOOK_SECRET` never leave the backend — not into a response,
not into a log, not into a prompt, not into a `VITE_`-prefixed frontend variable. Configuration
holds them as `SecretStr`; the logging pipeline masks configured secret values and any field whose
name looks like one. Both behaviours are tested, and a standing test scans frontend source for
secret-bearing names.

`RAZORPAY_KEY_ID` is public and is meant to reach the browser, at checkout time, in a response
body — never from configuration.

## Contributing rules

1. Never edit `architecture.md`. Record decisions in `docs/decisions/` instead.
2. Never trust model output for a price, SKU, stock level, compatibility claim, approval, or
   payment status. Read it from the database or from a verified webhook.
3. Keep business logic out of route handlers, and database access out of agent or MCP code.
4. Tests land with their milestone; the suite stays hermetic — no test reaches a real model or a
   real payment provider (`tests/conftest.py` enforces the latter now that real keys exist).
5. Test doubles that imitate Razorpay live only under `backend/tests/fixtures/`, never in
   application code.
