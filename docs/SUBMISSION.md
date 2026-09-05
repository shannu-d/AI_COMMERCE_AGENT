# Razorpay Buildathon — Track 1 submission

**Track:** AI Growth & Agentic Commerce
**Project:** EASY BUY — a merchant made transactable by AI, on Razorpay test-mode APIs

---

## 1. What it is, in one line

An AI shopping agent that takes a buyer from a natural-language request to a
**verified Razorpay payment**, plus an **MCP server** that lets an *external* AI
buyer do the same thing end to end — with every money action bounded, gated,
explained, and written to an append-only audit trail.

The whole system is built on one invariant, restated in every layer:

> **LLM proposes → application validates → user authorises → Razorpay executes → verified webhook confirms → system audits.**

## 2. How it meets the track

The brief accepts either "grow a merchant's revenue" or "make a merchant
transactable by an AI buyer, end to end". This project does the second, two ways:

| Track element | In this project |
| --- | --- |
| **Conversational in-app checkout** | `POST /api/chat` — a Groq agent (`openai/gpt-oss-120b`) with a bounded 8-tool loop. Discovery → cart → explicit approval → Razorpay Checkout → confirmed order. Live-verified with a real ₹999 test payment. |
| **Agent-readable catalogue** | The MCP server (`python -m app.mcp`, ADR-024) exposes `browse_catalog`, `search_catalog` (deterministic ranking), `get_product`, `get_compatible_products`, and an `easybuy://catalog` resource. |
| **Made transactable by an AI buyer** | The same MCP server's `create_quote` → `authorize_and_pay` → `get_order_status`. An external agent gets a merchant-computed quote, authorises a specific amount (an AP2/x402-style mandate), and receives a Razorpay checkout handoff. `authorize_and_pay` verified end to end against real Razorpay test mode. |
| **Upsell & cross-sell** | `get_upsell_candidates` — accessories the *merchant* recorded as related, filtered to compatible + in stock (R§15). Grounded in `product_relationships`, never "because it increases revenue". |
| **Grow the merchant's revenue** | A full merchant dashboard: catalogue, inventory, pricing, orders, revenue analytics (`/api/merchant/*`, `frontend/src/pages/merchant/`), behind its own authentication. A merchant can add a product and the agent sells it the same minute (verified). |

### "The bar" — every money action explainable, bounded, gated; audit trail; one failure handled

| The bar | Evidence |
| --- | --- |
| **Explainable** | The Policy Engine returns machine-readable reason codes; ranking results carry the engine's own reason and score; every audit row names the actor (`SYSTEM` / `RAZORPAY` / a user). |
| **Bounded** | 8 tool calls per turn max; a per-transaction spending limit (₹10,000); only LOW-risk tools execute; the MCP buyer authorises exactly one amount. |
| **Gated** | `create_order` is not a tool anywhere (checked four ways). A human's approval — or the MCP `authorize_and_pay` mandate — is a database `NOT NULL` constraint. A verified webhook is the *only* thing that marks an order paid. |
| **Audit trail** | `audit_events`, append-only, reconstructs any transaction. A real order from testing: `ORDER_CREATED → RAZORPAY_ORDER_CREATED → PAYMENT_WEBHOOK_RECEIVED → PAYMENT_FAILED → … → PAYMENT_CONFIRMED`, each attributed. |
| **One failure, gracefully** | Two, both verified live: **price drift** — approval invalidated, Razorpay order blocked, fresh approval + idempotency key required; **payment failure** — an international-card decline arrived as a real `payment.failed` webhook, order → `PAYMENT_FAILED`, cart kept intact, clean retry. |

## 3. The two demo paths

### A. Human buyer (browser)
1. `http://127.0.0.1:5173` → chat: *"a rugged case for an iPhone 16 under ₹1500"*
2. Grounded recommendations appear on the Smart Agent surface (deterministic ranking).
3. Add to cart → the total is the backend's. Approve the exact version + total.
4. **Pay now** → real Razorpay Checkout opens. Pay with **Netbanking → Success**, UPI `success@razorpay`, or a domestic card.
5. The order page flips `Verifying… → Payment confirmed` when the signed webhook lands.
6. Then show the **price-drift failure**: change a price in the merchant dashboard between approval and checkout → the order is refused with a reason code.

### B. AI buyer (MCP)
1. `python -m app.mcp` (or `--stdio` for an MCP client such as Claude Desktop / MCP Inspector).
2. `search_catalog("rugged case", category="phone_case", max_price="1500.00")` → ranked results.
3. `create_quote(items=[{"sku": "CASE-IP16-BLK", "quantity": 1}])` → `{quote_reference, total: "999.00"}`.
4. `authorize_and_pay(quote_reference, authorized_amount="999.00")` → a Razorpay order + `pay_url`.
5. `authorize_and_pay(quote_reference, authorized_amount="1.00")` → `{"status": "rejected", "code": "TOTAL_CHANGED"}` — the graceful failure, no charge.
6. `get_order_status(order_id)` → `paid` becomes true only after the webhook.

## 3a. Evidence in this repository

`pitch-assets/` holds 23 screenshots of the running system, in demo order: the storefront, the
agent answering and its grounded recommendations, the merchant dashboard, the approval step, the
Razorpay test-mode checkout including OTP, the confirmed payment, and the Razorpay dashboard
showing the same transaction from the provider's side.

The two walkthrough recordings (`website-demo.mp4`, `razorpay-dashboard-logs.mp4`) are **not in
this repository** — the first is 129 MB and GitHub refuses any file above 100 MB. They are supplied
alongside the submission.

## 4. Architecture (where authority lives)

```
Groq agent / MCP buyer → tool call → tool handler → service → repository → PostgreSQL
                                          │
                              deterministic ranking engine  (no model)
                                          │
             cart → approval / mandate → Policy Engine → order → Razorpay
                                                                    │
                                              verified webhook → payment truth → audit
```

- **PostgreSQL** owns product facts. The model never sets a price, SKU, or stock.
- **The ranking engine** owns relevance. It is pure — no model, no clock, no query — and reproduces `architecture.md`'s worked example exactly.
- **The Policy Engine** owns whether money may move. Ten rules, no I/O, machine-readable verdicts.
- **A verified Razorpay webhook** owns whether money *did* move.

## 5. Stack

Backend: Python, FastAPI, SQLAlchemy, PostgreSQL, Alembic. LLM: **Groq** (`openai/gpt-oss-120b`), locked (ADR-018). Payments: Razorpay test mode. Agent surface: MCP (FastMCP). Frontend: Vite + React + TypeScript, Assistant-UI for the chat runtime. Auth: argon2id + opaque bearer tokens (ADR-023).

**Tests:** backend **1,711 passing + 2 xfailed, 0 skipped** against a real PostgreSQL (the xfails are finding F-1, held strict so the defect stays visible); frontend **71 passing**; typecheck / lint / build clean. **25 architecture decision records** (ADR-000 template plus ADR-001 … ADR-024). Safety properties enforced by AST-walking tests, not convention.

## 6. Honest gaps

- **"Growth" is conversion + upsell, not automation** — no campaign orchestrator, abandoned-cart recovery, or personalisation loop.
- **The MCP server is unauthenticated and single-merchant** — money still can't move without the `authorize_and_pay` mandate + Policy Engine, but a real deployment needs per-buyer AP2 mandates.
- **Stock is not decremented when an order is paid.** Inventory eliminates at search and is
  re-read under `SELECT … FOR UPDATE` inside the order transaction, so nothing oversells against a
  stale read — but no code reduces `inventory.quantity` after `PAYMENT_CONFIRMED`, and
  `reserved_quantity` stays 0. ADR-005 defers the reservation lifecycle (open question C5).
  Measured: `SPRO-IP16-1` has 3 units across confirmed orders and still shows its seeded 40.
- **Buyer order history is thin.** `/account` lists a buyer's real orders (ownership derived from
  `orders.session_id → sessions.user_id`), but the response schema it reuses carries no
  `created_at` and no line items, so the page shows an order id, a status and a total — not the
  date or what was bought. The data is in `orders`/`order_items`; the buyer-facing schema does not
  expose it.
- **Not deployed** — runs locally; the webhook needs a tunnel (ngrok, documented).
- **Groq free tier ≈ 1 turn / 1–2 min** — a multi-turn live demo will rate-limit; the failure path is graceful but slow.
- Full ACP / AP2 / x402 protocol support is scoped out; `authorize_and_pay` is the mandate shape those formalise.

## 7. Run it

See [`docs/RUNBOOK.md`](RUNBOOK.md). In short: PostgreSQL + `alembic upgrade head` +
`python -m app.seed.circuitcraft`; backend on `:8004`; frontend on `:5173` with
`frontend/.env` → `:8004`; `python -m app.mcp` for the AI-buyer surface; an ngrok
tunnel to `:8004` for Razorpay webhooks, with the dashboard webhook secret matching
`RAZORPAY_WEBHOOK_SECRET`.

## 8. The story of the build

Decisions are in [`docs/decisions/`](decisions/) (24 numbered ADRs plus a template, append-only). Every
deviation from the spec is in [`docs/notes/deviations.md`](notes/deviations.md).
The defects found and fixed along the way — including on the final integration day
— are in [`docs/notes/bugs-found-during-development.md`](notes/bugs-found-during-development.md).
