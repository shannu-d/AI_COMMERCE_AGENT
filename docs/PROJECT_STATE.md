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

### Frontend F-phase status

| Phase | Status | Note |
| --- | --- | --- |
| **F0** scaffold | `COMPLETE` | Vite 6 + React 18 + TS 5.9, TanStack Query, Zod, Tailwind, Vitest. 11 tests, typecheck clean, production build succeeds. **Acceptance verified live**: browser-origin preflight + `GET /api/health` parsed by the real Zod schema |
| **F1** CORS + design system | `COMPLETE` | CORS live-verified (allowed origin echoed, foreign origin refused). Design tokens in `index.css`, primitives in `components/primitives.tsx` |
| **F2** chat core | `COMPLETE` | `ChatWindow`, `useChat`, session in `sessionStorage`. Turns serialised; business outcomes on HTTP 200 render as recovery flows |
| **F3** recommendations | `COMPLETE` | `RecommendationCard`/`Grid`. Rendered from `recommendations[]` only — a test asserts prose-only products yield no card |
| **F4** cart | `COMPLETE` | `CartPanel`. A test proves the total is the backend's even when it contradicts the line items |
| **F5** approval + policy failures | `COMPLETE` | `ApprovalDialog`. Submits displayed `cart_version` + `expected_total`; per-code recovery copy; 409 explained as a stale view |
| **F6** Razorpay checkout | `IN_PROGRESS` | `razorpay.ts` + `OrderPage` built; the success callback only triggers a re-read, never marks paid. **Live check still blocked on real Razorpay keys** |
| **F7** order status | `COMPLETE` | `OrderPage` at `/orders/:id`, polls until a terminal state, one banner per order state |
| **F8** responsive + a11y | `COMPLETE` | 11 a11y tests: labelled input, live-region transcript, modal dialog with Escape + focus, stock as text. Reduced-motion honoured globally |
| **F9** E2E + polish | `IN_PROGRESS` | 24 invariant/integration tests + an opt-in live suite (`npm run test:live`). **The money path is verified live**; the chat-driven variant is rate-limited (§11.3) |
| **F10+** storefront | `DEFERRED` | Needs new backend routes; scope decision still with the owner |

**F0–F9 are the decomposition *inside* M14** (`04-task-breakdown.md` FE-00..FE-07). They do not
replace or reorder M0–M15.

## 9. Test status

**Backend: 1292 passed · 0 failed · 0 skipped** (909 need no database).
**Frontend: 35 passed** (`cd frontend && npm run test`), typecheck clean, production build 287 kB.
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
- The frontend's `lint` script is dead: `package.json` declares `eslint .`, but eslint is neither a
  declared dependency nor configured (no `eslint.config.*`), so `npm run lint` fails on a clean
  checkout. CI therefore has no frontend lint step.
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

**Code work that needs neither:** F6/F9's remaining polish, wiring up eslint (the `lint` script is
declared but the tool is neither installed nor configured), and — if the storefront scope is ever
chosen — the three catalog-browsing routes in §20.C of the frontend spec. The scope decision (Phase 1 versus the storefront) is still open and still yours.
