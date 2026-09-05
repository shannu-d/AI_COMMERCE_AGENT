# Progress Report

**As of:** 2026-09-05 · **Last commit:** `c67186b` (+ uncommitted fixes, see *Working tree* below)
**This file is a high-level human-readable snapshot only.** The canonical current state is
**[`docs/PROJECT_STATE.md`](docs/PROJECT_STATE.md)** — if this file ever disagrees with it, that
file wins. For the Razorpay Buildathon Track 1 write-up see **[`docs/SUBMISSION.md`](docs/SUBMISSION.md)**.

> **2026-09-04:** The money path is **live** — a real Razorpay test-mode payment completed end to
> end (order → Checkout → signed webhook → `PAYMENT_CONFIRMED` → audit), and `payment.failed` was
> handled gracefully too. Authentication (ADR-023) is in. An **MCP server** (ADR-024,
> `python -m app.mcp`) makes the merchant sellable to an external AI buyer.

> **2026-09-04 (later):** **M15 is complete on the backend** — a 270-case commerce evaluation
> suite (`backend/tests/evals/`) runs the agent, the MCP surface and the money path against the
> real catalogue and the real Policy Engine. **268/270 pass**, 3,470 deterministic checks, and
> the hard-constraint and authorization pass rates are **100%**. See
> **[`docs/EVALUATION-REPORT.md`](docs/EVALUATION-REPORT.md)**.

> **2026-09-05:** **F-3 fixed** — the search tool now describes its own parameters and carries the
> merchant's real attribute names, so a stated requirement eliminates instead of merely ranking.
> Then the whole site was **driven in a browser from an empty session**, which found **four more
> defects that every test had passed over**. All five are fixed with regression tests; none could
> move money, and none touched the Policy Engine, the ranking engine, the schema or any validation
> rule. Detail: [`docs/notes/bugs-found-during-development.md`](docs/notes/bugs-found-during-development.md) §A2.

> 🔒 **LLM provider: Groq, locked (ADR-018).** Model `openai/gpt-oss-120b` — open weights,
> **served by Groq**, no request reaches OpenAI. Never propose migrating to Anthropic, Claude,
> OpenAI or Gemini. **Implemented and live-verified** (M4-R).

## What's built

| Milestone | What it is | Status |
| --- | --- | --- |
| M0 | Foundation (config, lint, pytest harness) | ✅ Complete |
| M1 | Catalog database (schema, migrations, seed) | ✅ Complete |
| M2 | Catalog read services | ✅ Complete |
| M3 | Ranking engine (deterministic recommendations) | ✅ Complete |
| M4 | LLM layer (intent extraction, tool schemas) | ✅ Complete |
| M5 | Agent runtime + `POST /api/chat` | ✅ Complete |
| M6 | Commerce schema (carts, orders, approvals, payments, audit — tables only) | ✅ Complete |
| M7 | Cart service + cart API | ✅ Complete |
| M8 | Approval model (`POST /api/cart/approve`) | ✅ Complete |
| M9 | Policy Engine (10 rules, pure, no DB) | ✅ Complete |
| M10 | Order creation + idempotency | ✅ Complete |
| M11 | Razorpay order client | ✅ **Complete — live-verified** (real test-mode order + payment) |
| **M4-R** | **Groq provider reconciliation (ADR-018)** | ✅ **Complete and live-verified** |
| M12 | Webhook handler (payment truth) | ✅ Complete — real Razorpay-signed webhooks verified (`payment.captured`, `payment.failed`, `order.paid`) |
| M13 | Audit log (durable transaction history) | ✅ Complete |
| M14 | Frontend | ✅ **F0–F8 done; F6 live-verified** (real Checkout). F9 polish partial |
| M15 | Integration scenarios + evaluation | ✅ Backend scenarios; money path live end to end; **270-case evaluation suite, 268 passing** |
| M16 | Catalogue expansion (51 products / 216 SKUs seeded) + Merchant Dashboard | ✅ Complete (ADR-021, ADR-022) |
| ADR-023 | Authentication & authorization (customers + merchants) | ✅ Implemented |
| ADR-024 | MCP surface — merchant sellable to an external AI buyer | ✅ Implemented and verified |

**Test suite:** backend **1,711 passed, 2 xfailed, 0 skipped** against a real PostgreSQL (the two
xfails are the recorded F-1 findings, kept strict so a fix cannot land silently); frontend **69
passed**, typecheck and lint clean. The Groq provider, CORS and the **entire money path**
(cart → approval → order → Razorpay → signed webhook → audit) are additionally verified against
live services by hand.

## The architectural spine, in one line

```
LLM proposes → application validates → user authorizes → Razorpay executes → system audits.
```

Every milestone above exists to make one link in that chain unbreakable by construction — not by
prompt wording:

- The model can never see a price, invent a SKU, or move money. `create_order` is not a registered
  tool anywhere in the codebase (checked four separate ways).
- No order can exist without a human's explicit approval — enforced by a database `NOT NULL`
  constraint, not just application logic.
- A price change between approval and checkout (in **either** direction) is caught and refused,
  with the reason shown to the buyer. Proven end to end in an integration test *and* live.
- Every step — cart created, user approved, policy passed/failed, order created, payment confirmed
  — is written to an append-only audit log that can reconstruct the whole story afterward.

That spine has now survived a 270-case evaluation, a live money path, an external AI buyer over
MCP, and a full browser walkthrough. **Every defect found in all of that was outside it.**

## Running it

Full instructions: **[`docs/RUNBOOK.md`](docs/RUNBOOK.md)**. In short — PostgreSQL on 5432, backend
on **8004** (port 8000 is an unrelated local app), frontend on **5173**, MCP on 8005, and `ngrok`
on 8004 if you want webhooks to arrive.

A merchant administrator is provisioned by an operator, never by a route:
`python -m app.admin.provision_merchant --email owner@easybuy.test`. Customers self-register at
`/register`.

## What I need from you

### 1. ~~React or Next.js~~ — decided: **Vite** (ADR-017) ✅

### 1b. ~~Phase 1 or Phase 2 frontend~~ — resolved: **Phase 2 is built** ✅

The storefront, order history and merchant dashboard that this file once listed as a fork needing
your decision all exist: home, category, product, cart, order and account pages, plus a seven-page
merchant dashboard (M16), on a real identity model (ADR-023 — which reopened ADR-006's "no users
table" deliberately, and recorded why).

### 2. ~~Real credentials~~ — all three are live ✅

Groq, `RAZORPAY_KEY_ID`/`RAZORPAY_KEY_SECRET` and `RAZORPAY_WEBHOOK_SECRET` are all real, all in
`.env`, and all verified against the live services. **The earlier version of this file claimed the
Razorpay keys were still `REPLACE_ME`; that was false and is what audit recommendation R4 was
about.**

One live constraint worth knowing for a demo: Groq's account limit is **8,000 tokens per minute**,
and one agent turn is two model calls totalling about 9,200 — so a turn now waits out the provider's
own `retry-after` (typically ~13s) and takes 15–25 seconds. That is the account's limit, not the
code's.

### 3. Open items, none blocking

Four recommendations from the 2026-09-03 audit remain open, and one has been promoted:

- **R9 — automated browser E2E (Playwright).** Filed as P2; now the highest-value item on the list.
  Four of the five defects fixed on 2026-09-05 were found by manually driving a browser and could
  only have been found that way.
- **R3** — validate `GROQ_API_KEY` at startup rather than per turn.
- **R8** — log a non-secret configuration fingerprint at startup, so a stale process is identifiable.
- **R6** — configure a git remote and let CI run. Needs your hosting decision.

Two evaluation findings also remain open, neither of which can move money: **F-1** (the assistant's
prose is not validated against the turn's own tool results — recorded as two strict `xfail`s) and
**F-2** (`recommend_many` / `combine(total_budget=…)` are built and reachable from no tool or route).

## Working tree

The 2026-09-05 fixes are **not yet committed**: the F-3 fix, the four walkthrough fixes, their
regression tests, and these documentation updates. `git status` shows them.

## Where the detail lives

- `docs/PROJECT_STATE.md` — canonical current state and next safe action.
- `docs/implementation-status.md` — the full narrative, milestone by milestone.
- `docs/notes/bugs-found-during-development.md` — every real defect found, and how.
- `docs/EVALUATION-REPORT.md` — the 270-case evaluation, its findings and its blind spots.
- `docs/audit/` — the 2026-09-03 engineering audit, with 2026-09-05 status addenda.
- `docs/decisions/README.md` — index of all 25 ADRs (ADR-000 through ADR-024).
- `docs/notes/deviations.md` — every place implementation resolved an ambiguity, with reasoning.
- `docs/notes/open-questions-status.md` — the original 45 analysis questions and their status.
