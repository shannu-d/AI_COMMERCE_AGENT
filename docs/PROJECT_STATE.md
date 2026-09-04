# PROJECT STATE

**Canonical current-state dashboard.** Read this second, immediately after `CLAUDE.md`.
If any other document disagrees with this file about *current state*, this file wins — except for
`architecture.md`, which is the specification and is never edited.

**Last verified:** 2026-09-02 · **Against commit:** `38232ea` (+ uncommitted work, see §16)
**Verified by:** full test suite, lint, and direct source inspection — not by reading prior docs.

---

## 1. Project identity

Conversational commerce agent for a single merchant catalog (**CircuitCraft**, 32 SKUs), built on
one invariant that every part of the specification restates:

> **LLM proposes → application validates → user authorizes → Razorpay executes → system audits.**

`architecture.md` (16,737 lines, six parts) is the specification and is **never edited**.

## 2. Repository root

```
L:\AI_COMMERCE          ← the ONLY project root
```

`L:\RazorPay\backend` is an **unrelated** SQLite prototype. Never inspect, import, copy, reference
or depend on it.

## 3. Locked architectural decisions

Decisions that are **not** open for reconsideration or recommendation-to-change.

| Decision | Value | Authority |
| --- | --- | --- |
| **LLM provider** | **GROQ — LOCKED.** Model `openai/gpt-oss-120b` (open-weights, **served by Groq**; no request reaches OpenAI). Never propose Anthropic, Claude, OpenAI, Gemini or any other provider. Permanent unless the owner explicitly changes it. | **ADR-018** (supersedes ADR-016) |
| Database | PostgreSQL only, in every environment including tests | ADR-002 |
| Money | `Decimal` + `NUMERIC(12,2)`; API/seed money is a **string**; minor units only inside `app/payments/` | ADR-008 |
| `create_order` as a tool | **Absent**, not registered-and-failing | ADR-009 |
| Payment truth | A verified Razorpay webhook, exclusively | ADR-012 |
| Frontend build tool | Vite + React 18 + TypeScript (not Next.js) | ADR-017 |
| Model testing | No test calls a live model, ever, on any provider | ADR-015 |

## 4. Current milestone

**M14 — Frontend.** Phase **F1 backend half is complete** (CORS). The frontend application itself
does not exist yet.

**M4-R (Groq provider reconciliation) is COMPLETE and live-verified** — see §16. M14 is now the
only milestone in progress that is not blocked on credentials.

## 5–8. Milestone table

Status vocabulary is exactly: `NOT_STARTED` · `IN_PROGRESS` · `COMPLETE` · `BLOCKED` · `DEFERRED`.
**COMPLETE requires verified exit criteria and passing tests — not merely that code exists.**

| ID | Name | Status | Depends on | Implementation | Tests | Exit criteria | Key files | ADRs | Known issues |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| **M0** | Foundation | `COMPLETE` | — | Config, logging, lint, pytest harness, app factory | ✅ | ✅ App boots; health endpoint responds | `app/config.py`, `app/main.py` | — | — |
| **M1** | Catalog schema + seed | `COMPLETE` | M0 | 7 spec tables + `compatibility_targets`; 4 migrations; 32-SKU seed | ✅ 99 db + 43 seed | ✅ Migration up/down clean; seed idempotent | `migrations/versions/000{1..4}`, `app/seed/` | ADR-002, ADR-003 | — |
| **M2** | Catalog read services | `COMPLETE` | M1 | Catalog / Compatibility / Inventory services + repositories | ✅ (in 333 services) | ✅ Device+budget returns correct filtered set | `app/services/`, `app/repositories/` | ADR-002, ADR-003 | **No HTTP routes** — service-level only, by design |
| **M3** | Ranking engine | `COMPLETE` | M2 | Hard constraints, 4 scorers, weighted aggregator, Top-K | ✅ 142 | ✅ R§10 worked example reproduces `0.796800` / `0.786800` exactly | `app/ranking/` | ADR-004, ADR-005 | — |
| **M4** | LLM layer | `COMPLETE` | M0 | Client boundary, intent schema/extraction, prompts, 8 tool schemas | ✅ 215 | ✅ Text → validated intent, offline-testable | `app/llm/` | ADR-015, ~~ADR-016~~, **ADR-018** | — |
| **M4-R** | **Groq provider reconciliation** | `COMPLETE` | M4 | `GroqClient`, `GROQ_*` settings, dependency swap, guards inverted | ✅ 14 defect regression tests | ✅ **Live-verified**: real tool call + full chat turn | `app/llm/client.py`, `app/config.py`, `pyproject.toml` | **ADR-018** | Free tier = 8k TPM, ~1 turn/min |
| **M5** | Agent runtime (read-only) | `COMPLETE` | M3, M4 | Runtime loop, registry, executor, tools T-1..T-4, `POST /api/chat` | ✅ 178 agent + api | ✅ **Verified LIVE** — grounded Top-3 for the flagship query | `app/agent/` | ADR-009, ADR-010 | — |
| **M6** | Commerce schema | `COMPLETE` | M1 | 9 remaining ADR-006 tables (migration `0004`) | ✅ | ✅ FK integrity passes | `migrations/versions/0004` | ADR-006 | — |
| **M7** | Cart | `COMPLETE` | M6 | Cart service, versioning, authoritative totals, cart APIs | ✅ | ✅ Backend-computed total; version increments | `app/services/cart_service.py`, `app/api/routes/cart.py` | ADR-006 | — |
| **M8** | Approval | `COMPLETE` | M7 | Approval bound to cart+version+total; stale detection | ✅ | ✅ Stale approval rejected | `app/api/routes/cart.py` (`/cart/approve`) | ADR-007 | — |
| **M9** | Policy Engine | `COMPLETE` | M8 | 10 rules, pure, no DB, reason codes | ✅ 38 | ✅ Price-drift and OOS fail with correct codes | `app/policy/` | ADR-011 | — |
| **M10** | Orders + idempotency | `COMPLETE` | M9 | Order service, state machine, idempotency lifecycle | ✅ | ✅ Duplicate request → one logical order | `app/services/order_service.py`, `app/api/routes/orders.py` | ADR-013 | — |
| **M11** | Razorpay orders | `IN_PROGRESS` | M10 | ✅ Code complete | ✅ 20 (against doubles) | ❌ **Live test-mode order never created** | `app/payments/razorpay_client.py` | ADR-011 | Needs real Razorpay test keys (§14) |
| **M12** | Webhook | `COMPLETE` | M11 | Raw-body capture, signature verify, event dedupe | ✅ | ✅ Bad signature rejected; duplicate → one transition | `app/api/routes/webhooks.py`, `app/services/webhook_service.py` | ADR-012 | Live signature check unperformed (§14) |
| **M13** | Audit + trace | `COMPLETE` | M12 | Audit service, 12 named events, agent trace | ✅ | ✅ Transaction fully reconstructable | `app/services/audit_service.py` | ADR-010 | No HTTP read route (by design) |
| **M14** | Frontend | `IN_PROGRESS` | M5, M7, M8, M11 | **F0–F5, F7, F8 COMPLETE**; F6 and F9 need Razorpay keys | ✅ 15 CORS + 5 contract + 35 frontend | 🟡 F§33 met except the 3 Razorpay items | `frontend/` | **ADR-017** | Port 8000 conflict (§11.4) |
| **M15** | Integration & evaluation | `IN_PROGRESS` | M14 | ✅ Backend scenarios (12 tests) | ✅ 12 | ❌ Frontend half blocked on M14 | `tests/integration/` | ADR-014 | — |
| **M16** | Catalogue expansion + Merchant Dashboard | `COMPLETE` | M2, M10, M14 | **Catalogue → 51 products / 216 SKUs / 24 categories** across electronics + clothing + furniture, **no migration** (ADR-021). **Merchant Dashboard**: `merchant_service.py` (write + analytics), `OrderService.list_for_merchant`, `/api/merchant/*` (12 endpoints), `frontend/src/pages/merchant/` (7 pages) + `MerchantShell` (ADR-022) | ✅ +33 backend, +7 frontend | ✅ Cross-category agent, merchant create/restock/reprice round-trips, isolation rejected — all browser-verified | `app/services/merchant_service.py`, `app/api/routes/merchant.py`, `frontend/src/features/merchant/`, `app/seed/data/catalog.json` | **ADR-021**, **ADR-022** | No merchant auth (single-tenant); no merchant activity log; Razorpay still unconfigured so revenue reads ₹0 |

### Frontend F-phase status

| Phase | Status | Note |
| --- | --- | --- |
| **F0** scaffold | `COMPLETE` | Vite 6 + React 18 + TS 5.9, TanStack Query, Zod, Tailwind, Vitest. 11 tests, typecheck clean, production build succeeds. **Acceptance verified live**: browser-origin preflight + `GET /api/health` parsed by the real Zod schema |
| **F1** CORS + design system | `COMPLETE` | CORS live-verified (allowed origin echoed, foreign origin refused). Design tokens in `index.css`, primitives in `components/primitives.tsx` |
| **F2** chat core | `COMPLETE` | `ChatWindow`, `useChat`, session in `sessionStorage`. Turns serialised; business outcomes on HTTP 200 render as recovery flows |
| **F3** recommendations | `COMPLETE` | Rendered from `recommendations[]` only — a test asserts prose-only products yield no card. **Since ADR-020 (§8b)** the cards render on the `/agent` surface (`SmartAgentRecommendations`), not in the transcript; the chat shows a pointer to them |
| **F4** cart | `COMPLETE` | `CartPanel`. A test proves the total is the backend's even when it contradicts the line items |
| **F5** approval + policy failures | `COMPLETE` | `ApprovalDialog`. Submits displayed `cart_version` + `expected_total`; per-code recovery copy; 409 explained as a stale view |
| **F6** Razorpay checkout | `IN_PROGRESS` | `razorpay.ts` + `OrderPage` built; the success callback only triggers a re-read, never marks paid. **Live check still blocked on real Razorpay keys** |
| **F7** order status | `COMPLETE` | `OrderPage` at `/orders/:id`, polls until a terminal state, one banner per order state |
| **F8** responsive + a11y | `COMPLETE` | 11 a11y tests: labelled input, live-region transcript, modal dialog with Escape + focus, stock as text. Reduced-motion honoured globally |
| **F9** E2E + polish | `IN_PROGRESS` | 24 invariant/integration tests + an opt-in live suite (`npm run test:live`). **The money path is verified live**; the chat-driven variant is rate-limited (§11.3) |
| **F10+** storefront | `DEFERRED` | Needs new backend routes; scope decision still with the owner |

**F0–F9 are the decomposition *inside* M14** (`04-task-breakdown.md` FE-00..FE-07). They do not
replace or reorder M0–M15.

### 8a. Homepage visual pass (2026-09-03)

The homepage and shared header were brought in line with an owner-supplied reference screenshot
(`reference/1.png`). Frontend only — no backend, API, schema, Groq, Razorpay or policy change.

- **Storefront brand is now "EASY BUY"** (owner decision, 2026-09-03). The wordmark, `<title>`,
  meta description, footer and hero eyebrow use it; `CircuitCraft` stays as the merchant/catalogue
  name in product data (`brand` field) and in `architecture.md`, which is unchanged.
- **The accent token `--volt` changed from `#CCFF00` to `#94DD26`** (`src/index.css`), the
  reference's interaction colour. It still appears only on interaction and emphasis — the active
  nav item, hover states (nav, categories, quick prompts, "see everything", the hero CTA), the
  wordmark, the concierge marker and Send button, the headline underline. The surface stays paper /
  ink / grey. No new gradients, shadows, glassmorphism or rounded cards.
- **Header (`src/layout/Shell.tsx`)** rebuilt to the reference composition: EASY BUY wordmark +
  cart glyph (left), centred primary nav **Home / Shopping / Smart Agent / Services** (Smart Agent
  links to `/agent` — see §8b; Services scrolls to the footer), and **Concierge / Cart / More /
  Account** controls (right). "More" and the account control are `HeaderMenu` disclosures; their
  items are honest placeholders that raise a toast ("not part of this demo yet"). A thin **category
  bar** now sits under the header on every breakpoint (it was desktop-nav on large screens, a
  separate rail only on mobile before).
- **Motion**: unchanged primitives. Entrances still use the CSS `rise`/`fade` keyframes
  (`transform`/`opacity` only); new hovers are `transition-colors` at `--dur-fast`. The global
  `prefers-reduced-motion` block still neutralises all of it. No JS animation loops added.
- **Responsive**: verified on desktop (~1536 px) in-browser; the automation environment could not
  resize below that, so 390/768/1024 px were validated by DOM/breakpoint inspection, not visually.
  The header uses `grid-cols-[1fr_auto_1fr]`; below `lg` the primary nav folds into one menu and
  the category bar scrolls horizontally.
- Frontend suite **42 passed** at the time of this pass, typecheck + eslint clean, production build
  succeeds.

### 8b. Smart Agent recommendations surface (2026-09-04)

The agent's product cards moved out of the chat transcript into a dedicated surface (**ADR-020**,
deviation D8). Frontend + one backend prompt change; no chat/cart/order contract change.

- **`recommendations[]` is already the structured contract** (`ChatResponse`, mirrored in
  `api/schemas.ts`). Nothing about it changed. The change is where those objects render.
- **New `/agent` route → `AgentPage`** renders `SmartAgentRecommendations` (the grid) beside the
  concierge rail. `useAgentRecommendations` derives `{ recommendations, status, retry }` from the
  app-wide `AgentTurnsContext` — no new store. Statuses: `idle` (discovery) / `loading` (skeleton,
  or previous cards dimmed) / `ready` / `empty` (no-match) / `error` (retry). Cards are the
  existing `ProductCard`/`ProductGrid` via `fromRecommendation`; `useAddToCart` untouched.
- **`ChatWindow` no longer renders the grid** — it shows prose plus a one-line
  *"N products in your recommendations →"* pointer to `/agent`. F§9 preserved: no card, and no
  pointer, is fabricated from prose. `features/chat/RecommendationCard.tsx` deleted (redundant).
- **Stale-request guard**: each run stamps a monotonic `seq` at start; the selector picks
  `max(seq)`, not last-appended (`pickLatestTurn`, pure, tested). Runs are serialised today; this
  makes the guarantee explicit.
- **`Concierge.ask()` navigates to `/agent`** so a homepage hero / quick-prompt ask lands where the
  cards are. Bare `open()` (header, mobile launcher) stays put.
- **Backend**: `system_prompt.md` gained a "Writing your reply" section (be brief, no tables, name
  products with prices) — version `1.0.0` → `1.1.0`. Prompt-content asserted in `test_prompts.py`.
  Not a control (L§29 / ADR-009). A running backend must be restarted to load it.
- **Tests**: frontend **50 passed** (+8: transcript-pointer-not-cards, panel renders per
  recommendation, empty state, error/retry, set replacement, `pickLatestTurn` ordering); backend
  no-db **917 passed**, chat/llm/agent **407 passed** (8 pre-existing PostgreSQL skips). typecheck,
  eslint, build green. Bundle 564 kB (no new dependency).
- **Browser-verified** on port 8004: five grounded cards in the panel at backend prices/labels,
  transcript = prose + pointer, add-to-cart → `POST /api/cart/items` 200 (cart total ₹3,697.00),
  quick-prompt → `/agent`, rate-limit/malformed-response → retry state not a crash.

### 8c. Catalogue expansion + Merchant Dashboard (M16, 2026-09-04)

Two owner-requested additions; see **ADR-021** and **ADR-022**, and `deviations.md` D9/D10.

- **Catalogue** grew to **51 products · 216 SKUs · 24 categories** — electronics (the original
  prototype, unchanged and now pinned by `test_the_original_electronics_prototype_is_preserved`),
  **clothing** (`t_shirt`/`shirt`/`jeans`/`hoodie`/`jacket`/`dress`, colour × size variants) and
  **furniture** (`chair`/`table`/`desk`/`sofa`/`bed`/`shelving`). **No migration** — the model is
  JSONB-attribute and the ranking/filter/tool/service layers are category-agnostic by design.
  Merchant display name → `EASY BUY` (`DEFAULT_MERCHANT_ID` unchanged).
- **Backend**: `app/services/merchant_service.py` — `MerchantCatalogService` (create/update/archive
  product & variant, `set_stock`, `create_category`, paginated list) + `MerchantAnalyticsService`
  (real aggregates; revenue = `PAYMENT_CONFIRMED` only). `OrderService.list_for_merchant` (read).
  `app/api/routes/merchant.py` — 12 endpoints under `/api/merchant`, merchant resolved
  server-side, `extra="forbid"` (no `merchant_id` field anywhere) = the isolation guarantee. The
  pure read services stay read-only.
- **Frontend**: `frontend/src/features/merchant/` (api + Zod schemas, hooks, `MerchantShell`,
  `DashTable`, attribute templates) and `frontend/src/pages/merchant/` — Overview, Products,
  Product editor, Inventory, Orders (+ detail), Categories, Settings. `/merchant/*` is its own
  layout route; reuses the design system; one inline-SVG bar, no chart library.
- **Groq**: unchanged. Verified live — the agent answers clothing and furniture queries through the
  same `search_catalog` tool and ranking engine, with the concise ADR-020 reply.
- **Known limitations**: no merchant authentication (single-tenant, documented on the Settings
  page); no merchant activity log; Razorpay unconfigured so `paid_orders`/`revenue` read zero.

## 9. Test status

**Backend: 1344 passed · 0 failed · 0 skipped** with a database (was 1311 before M4-R/ADR-020/M16
work landed on this branch; 917 need no database). Run with
`TEST_DATABASE_URL=postgresql+psycopg://ai_commerce:ai_commerce@127.0.0.1:5432/ai_commerce_test`.
**Frontend: 57 passed** (`cd frontend && npm run test`), typecheck clean, eslint clean, production
build ~566 kB (gzip ~164 kB, no new dependency).
The Assistant UI runtime (ADR-019) added 7 tests and grew the bundle from 287 kB to 518 kB; ADR-020
added 8 tests and ~2 kB.
**Live money path: verified** (`npm run test:live`, opt-in, needs a running backend).

```bash
cd backend
TEST_DATABASE_URL="postgresql+psycopg://ai_commerce:ai_commerce@127.0.0.1:5432/ai_commerce_test" \
  .venv/Scripts/python.exe -m pytest -q
```

⚠️ **Use `127.0.0.1`, not `localhost`.** The throwaway PostgreSQL binds IPv4-only; `localhost`
resolves to `::1` first and the whole `requires_db` suite silently skips. **A run showing skips is
an incomplete run, not a pass.**

By area: services 333 · llm 201 · agent 178 · ranking 142 · db 99 · api 98 · seed 43 · policy 38 ·
payments 20 · integration 12.

## 10. Last verification status

| Check | Result |
| --- | --- |
| `pytest` (full, with DB) | ✅ 1273 passed, 0 skipped |
| `ruff check .` | ✅ All checks passed |
| `ruff format --check .` | ✅ Clean (168 files) |
| `npm run test` / `typecheck` / `build` (frontend) | ✅ 11 passed, tsc exit 0, build 240 kB |
| CI workflow | 🟡 **Added 2026-09-03, never executed on a runner** — no git remote exists. Validated locally: YAML parses, `ruff check`/`format --check` clean, and the skip-guard was verified in both directions (23 skipped → build fails; 0 skipped → passes) |
| CORS from a browser origin | ✅ **Verified live**: preflight 200 with `allow-origin`; foreign origin gets no header |
| Money path, end to end | ✅ **Verified live**: cart Rs.598.00 -> stale version 409 -> wrong total 409 -> approval -> order -> idempotent replay returns the SAME order; 598.00 == 59800 minor |
| Chat-driven flagship, end to end | 🟡 **Partially.** A single turn returns grounded recommendations, but a full tool-loop turn exceeds the 8k TPM tier (§11.3) |
| Assistant UI agent chat | ✅ **Verified live in a browser 2026-09-03.** Real Groq turn → 3 grounded cards at the backend's prices (₹999.00 ×2, ₹1,299.00 `Low stock`) → add-to-cart → cart v2 total ₹999.00 → approval dialog. A mid-test Groq `429` rendered as the designed calm recovery, not a crash |
| Live Groq call | ✅ **Performed 2026-09-02.** `models.list()`, a direct tool-calling completion, and a full `POST /api/chat` turn returning 3 grounded recommendations |
| Live Razorpay test order | ❌ **Never performed** — placeholder credentials |
| Live webhook signature | 🟡 **Application path verified live 2026-09-03**, over a public ngrok tunnel to a locally-running backend: bad signature → `400 {"status":"rejected"}`; a correctly signed event for an unknown order → `200 {"status":"received"}`; the same event replayed → `200 {"status":"ignored"}`, leaving **one** `webhook_events` row and three audit rows (`WEBHOOK_SIGNATURE_REJECTED`, `PAYMENT_WEBHOOK_RECEIVED`, `WEBHOOK_DUPLICATE_IGNORED`). Signed with the `REPLACE_ME` placeholder, **not** a Razorpay-issued secret, and **not** a delivery Razorpay actually sent — both of those remain unverified |

## 11. Known bugs

1. ~~`.env` provider configuration broken~~ — **fixed in M4-R.** `GROQ_API_KEY` / `GROQ_MODEL`.
2. ~~Two standing tests forbid Groq~~ — **fixed in M4-R**, inverted rather than deleted.
3. **Groq free tier: 8,000 tokens/minute.** One agent turn costs roughly 5,000 (a large system
   prompt plus eight tool schemas, then a follow-up carrying tool results), so back-to-back turns
   hit `429`. The retry path handles it correctly and the buyer sees a calm generic message, but
   **sustained demo use needs a higher Groq tier**. An account matter, not a code defect. It will
   affect M14's demo and any M15 scenario that chains turns.
4. **The agent's tool loop makes three model calls per turn**, each carrying the system prompt plus
   eight tool schemas. Against the 8,000 TPM tier that is roughly one turn per *two* minutes, and
   the three bounded retries land inside the same window. The failure path is correct — the buyer
   sees a calm retryable message and no provider text leaks — but **the chat-driven flagship
   scenario cannot be demonstrated reliably on the current Groq tier.** The money path is
   unaffected: cart, approval, order and idempotency use no model at all, and are verified live.
5. **Port 8000 is occupied by an unrelated application on this machine.** A different `uvicorn`
   (PID observed: 25724, `-m uvicorn app.main:app --port 8000 --reload`) answers `/api/health` with
   `{"status":"healthy","llm_provider":"mock","mock_payments_enabled":true}` — a shape that exists
   nowhere in this repository, almost certainly the unrelated `L:\RazorPay\backend` prototype.
   **Consequence:** starting this project's API on the default port fails with `errno 10048`, and a
   frontend left on the default `VITE_API_BASE_URL` will talk to the wrong backend. The Zod boundary
   catches it as `MALFORMED_RESPONSE` rather than showing wrong data, which is the protection
   working, but the message does not say "wrong server". Verification for F0 was therefore done on
   **port 8001**. Nothing was done to the other process — it is not this project's to stop.
6. **`POST /orders/{id}/checkout` has no `response_model`.** Returns a plain `dict`, so its shape is
   absent from the OpenAPI document. Cosmetic; blocks nothing.

## 12. Known technical debt

- `anthropic` is uninstalled and undeclared; a standing test asserts it stays that way.
- ~~The frontend's `lint` script is dead~~ — **resolved 2026-09-03.** eslint 9 with a flat config
  (`frontend/eslint.config.js`), and CI runs it with `--max-warnings 0`.
- No catalog-browsing HTTP routes. The services exist and are tested; nothing routes to them. This
  is **new scope**, not unfinished M2 work.
- `AuditService.reconstruct_order` / `.reconstruct_session` are complete and fully tested but have
  no HTTP route.

## 13. Open questions

| ID | Question | Status |
| --- | --- | --- |
| ~~Groq model~~ | — | **CLOSED**: `openai/gpt-oss-120b`, confirmed by the owner and live-verified |
| **FE scope** | Phase 1 (F0–F9) only, or the full storefront (F10+)? | **Needs owner decision.** Proceeding on Phase 1 |
| F4 | CI pipeline | **CLOSED** 2026-09-03 — `.github/workflows/ci.yml`. Never yet run on a runner (no remote configured), see §10 |
| F5, F8, F10 | Deployment, perf targets, i18n | OPEN — out of MVP scope |
| F9 | Evaluation harness format | OPEN — blocks M15's eval suite |
| F11 / U2 | The external brief | OPEN — needs external input |

## 14. Missing credentials / configuration

| What | Variable | Current | Blocks |
| --- | --- | --- | --- |
| ~~Groq API key~~ | `GROQ_API_KEY` | ✅ **Set and verified working** | — |
| ~~Groq model~~ | `GROQ_MODEL` | ✅ `openai/gpt-oss-120b`, verified | — |
| Razorpay key id | `RAZORPAY_KEY_ID` | `rzp_REPLACE...` | M11 exit; F6 live check |
| Razorpay secret | `RAZORPAY_KEY_SECRET` | `REPLACE_ME` | M11 exit; F6 live check |
| Razorpay webhook secret | `RAZORPAY_WEBHOOK_SECRET` | `REPLACE_ME` | A **Razorpay-issued** signature check. The application's own verification path was exercised live on 2026-09-03 by signing against the placeholder — see §10 |

All Razorpay values are **test-mode** keys — free, no real money.

## 15. Important deviations from architecture.md

`architecture.md` is never edited; deviations live in `docs/decisions/` and are indexed in
`docs/notes/deviations.md`.

1. **Provider (largest deviation).** L§44/L§48 name Claude Sonnet; L§50 and A§56 make
   `[ ] Claude Sonnet connected` a checkbox. **Groq is used instead, by owner decision (ADR-018).**
   Those four items are permanently unsatisfiable as literally written and are re-read
   provider-neutrally. The invariant they protect is provider-independent.
2. **Frontend scope.** F§3 says *"do NOT build a large e-commerce UI"*; `docs/frontend/` specifies a
   full storefront. Split into Phase 1 / Phase 2; unresolved pending §13.
3. **No streaming** (ADR-010), against F§28's implication of granular tool status.
4. **`sessions` / `session_messages` arrived in M5, not M6** (deviation A28).
5. **No `users` table** (ADR-006) — sessions are anonymous, which is why order history needs a new
   backend subsystem.

## 16. Recent implementation summary

**Uncommitted working tree** (nothing since `38232ea` has been committed):

- **F0 — frontend scaffold, COMPLETE.** `frontend/` on Vite 6 + React 18 + TypeScript 5.9, with
  TanStack Query, Zod, React Router, Tailwind and Vitest. The API boundary is the substantive part:
  every response is parsed through a Zod schema, money is a fixed-scale **string** that nothing sums
  or rounds, and a business outcome carried on HTTP 200 (a policy refusal, an out-of-stock finding)
  is deliberately **not** thrown as an error, so recovery flows never land in a component's
  network-error branch. 11 tests; typecheck clean; production build 240 kB.
  - Two bugs found and fixed during the scaffold: my first draft of the error vocabulary invented
    four codes that do not exist (`CATEGORY_NOT_FOUND`, `CART_VERSION_STALE`, `APPROVAL_EXPIRED`,
    `SPENDING_LIMIT_EXCEEDED`) — corrected against `app/agent/errors.py`; and Vitest 2 bundled its
    own Vite 5, which broke typechecking against Vite 6 (upgraded to Vitest 3).
  - A new backend test, `tests/api/test_frontend_contract.py`, reads the frontend's hand-mirrored
    error-code array and fails if it ever diverges from `ApiErrorCode`, plus asserts no secret-bearing
    name appears in frontend source. Verified by deliberately introducing a drift and watching it
    fail. It skips when the frontend is absent, so the backend suite stays standalone.
- **M4-R — Groq provider reconciliation, COMPLETE and live-verified.** `GroqClient` replaces
  `AnthropicClient`; dependency, settings and env variables renamed; the system prompt is now the
  first **message** (a top-level field is silently ignored on an OpenAI-compatible API); token usage
  read under `prompt_tokens`/`completion_tokens`. All five historical defects have named regression
  tests, and both anti-Groq guards were **inverted, not deleted**.
- **First live provider verification in the project's history.** A full chat turn returned
  `state=RECOMMENDING` with three grounded recommendations at real catalog prices (AeroCase Pro
  Rs.999.00 x2, ShieldCase Premium Rs.1299.00 `LOW_STOCK`) — M5's exit condition, proven live.
- **M14/F1 backend half** — CORS, with a pydantic-settings bug found and fixed
  (`Annotated[list[str], NoDecode]`).
- **ADR-017** (Vite, closes F6), **ADR-018** (Groq locked), ADR-016 superseded, and this file plus
  the Session Continuity Protocol created.

## 17. Next safe action

**Two things need you, and both are account-level rather than code:**

1. **Razorpay test keys** — the last three F§33 items (`Razorpay Test Checkout opens`, `payment can
   be tested`, `successful Policy PASS reaches Razorpay`) and M11's exit condition. The code path is
   built and unit-tested against doubles; only the live check is outstanding.
2. **A higher Groq tier**, if the chat-driven demo needs to run more than about one turn per two
   minutes. Nothing is broken at the current tier; it simply throttles.

**Code work that needs neither:** F6/F9's remaining polish, and — if the storefront scope is ever
chosen — the three catalog-browsing routes in §20.C of the frontend spec. The scope decision (Phase 1 versus the storefront) is still open and still yours.
