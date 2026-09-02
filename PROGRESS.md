# Progress Report

**As of:** 2026-09-02 · **Last commit:** `38232ea` (plus uncommitted M14/F1 work)
**This file is a high-level human-readable snapshot only.** The canonical current state is
**[`docs/PROJECT_STATE.md`](docs/PROJECT_STATE.md)** — if this file ever disagrees with it, that
file wins. For detail see `docs/implementation-status.md`, `docs/decisions/README.md` and
`docs/notes/open-questions-status.md`.

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
| M11 | Razorpay order client | 🟡 Code complete; live check unperformed |
| **M4-R** | **Groq provider reconciliation (ADR-018)** | ✅ **Complete and live-verified** |
| M12 | Webhook handler (payment truth) | ✅ Complete |
| M13 | Audit log (durable transaction history) | ✅ Complete |
| M15 | Integration scenarios — **backend half only** | ✅ Complete (INT-05, INT-06, INT-09, price-drift flagship, success path, duplicate submission, injection containment) |
| M14 | Frontend | 🟡 **F0-F5, F7, F8 done. F6/F9 blocked on Razorpay keys** |
| M15 | Integration scenarios — **frontend half** | ⛔ Waiting on M14 |

**Test suite:** backend 1292 pass against a real PostgreSQL, 0 failures, 0 skips (909 need no
database); frontend 35 pass, typecheck clean, production build OK. The Groq provider, CORS, and
the **entire money path** (cart -> approval -> order -> idempotent replay) are additionally
verified against live servers by hand.

## The architectural spine, in one line

```
LLM proposes → application validates → user authorizes → Razorpay executes → system audits.
```

Every milestone above exists to make one link in that chain unbreakable by construction — not by
prompt wording. Concretely, as of M13:

- The model can never see a price, invent a SKU, or move money. `create_order` is not a registered
  tool anywhere in the codebase (checked four separate ways).
- No order can exist without a human's explicit approval — enforced by a database `NOT NULL`
  constraint, not just application logic.
- A price change between approval and checkout (in **either** direction) is caught and refused,
  with the reason shown to the buyer. This was proven end-to-end in an integration test.
- Every step of a transaction — cart created, user approved, policy passed/failed, order created,
  payment confirmed — is written to an append-only audit log that can reconstruct the whole story
  afterward.

## What I need from you

### 1. ~~A decision: React or Next.js~~ — decided: **Vite** (ADR-017)

You didn't pick, so I went with the recommendation and wrote it up as a reversible decision rather
than leaving M14 stalled. **The recommendation changed on inspection**, and the earlier version of
this file had it wrong.

I previously recommended Next.js, reasoning that an SSR framework keeps `RAZORPAY_KEY_SECRET`
server-side. Then I read what the backend actually hands the browser:
`RazorpayClient.checkout_config()` returns the **public** key ID, an amount, a currency and a
provider order ID. That's all. The frontend never receives a secret, so Next.js's server layer would
be protecting nothing — and with no SEO requirement and no server-rendering need either, it's a
layer paid for and unused, against `architecture.md` F§3's explicit "keep the frontend small".

**So: React 18 + TypeScript on Vite, with React Router.** Reasoning in full in
`docs/decisions/ADR-017-frontend-framework-and-browser-access.md`. Say the word if you want Next.js
and I'll switch — nothing is scaffolded yet, so the cost of reversing is currently zero.

### 1b. A scope decision I still need from you

`docs/frontend/00-architecture-and-ux-specification.md` describes two possible frontends, and this
one is a real fork rather than a default I should pick:

- **Phase 1 (F0–F9)** — chat, recommendations, cart, approval, Razorpay checkout, order status.
  This is exactly the MVP `architecture.md` §3 specifies, and it needs **zero further backend work**.
- **Phase 2 (F10+)** — a full storefront with browse/category/product pages, and beyond that order
  history and a merchant dashboard. The browsing pages need three new backend routes (the services
  already exist, only HTTP routing is missing). History and the dashboard need a buyer identity
  model, which **ADR-006 deliberately closed** as "no users table" — reopening that is a backend
  architecture decision, not a frontend one.

I'm proceeding on **Phase 1** unless you say otherwise. It's a prefix of Phase 2, so nothing built
under it is wasted if you later want the storefront.

### 2. Real credentials (blocks three specific things — everything else works without them)

Three separate live checks are sitting undone because this machine doesn't have real API keys.
None of them block further development — the code paths are built and tested against fakes/doubles
— but the specification calls them out as things that must actually be verified once, by hand,
against the real services:

| What | Env var(s) | Currently | What it unblocks |
| --- | --- | --- | --- |
| ~~Groq~~ | `GROQ_API_KEY`, `GROQ_MODEL` | ✅ **Done.** Your key works; model `openai/gpt-oss-120b`; a full chat turn verified live. Note: the free tier is 8,000 tokens/min, about one agent turn per minute — a demo firing several turns quickly will see rate-limit messages. | — |
| Razorpay | `RAZORPAY_KEY_ID`, `RAZORPAY_KEY_SECRET` | Still placeholder `REPLACE_ME` in `.env` | Verifying a real test-mode Razorpay order gets created (M11's stated exit condition), and 3 of 16 frontend "definition of done" items in M14 (`Razorpay Test Checkout opens`, `payment can be tested`, `successful Policy PASS reaches Razorpay`) |
| Razorpay webhook | `RAZORPAY_WEBHOOK_SECRET` | Still placeholder | Verifying real webhook signatures from Razorpay's dashboard, once you have a checkout to test against |

**These are all Razorpay *test mode* keys** — free to generate from a Razorpay dashboard, no real
money involved. If you'd rather I proceed without them, that's fine: I'll keep building and keep
these three items explicitly marked open in the status doc, exactly as I have been.

### 3. Nothing else is blocking

No other decision, credential, or input is needed to continue. The scope question in #1b is the only
one where your answer changes what I build; I'm proceeding on Phase 1 meanwhile.

## Where the detail lives

- `docs/implementation-status.md` — the full narrative, milestone by milestone, including every
  test-scaffolding defect found and fixed along the way.
- `docs/decisions/README.md` — index of all 17 ADRs (architectural decisions the spec left open).
- `docs/notes/deviations.md` — every place implementation had to resolve an ambiguity, with reasoning.
- `docs/notes/open-questions-status.md` — the original 45 analysis questions and their current status.
