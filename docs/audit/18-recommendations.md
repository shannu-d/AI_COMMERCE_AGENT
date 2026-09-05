# 18 — Recommendations

Ordered by priority. Each states the problem, why it matters, the evidence, the fix, and whether it
blocks the project.

> **The list below is the audit as written on 2026-09-03 and is not rewritten.** What has since
> happened to each item is the table immediately following. Where a recommendation was met by a
> different route than the one it proposed, the table says so rather than pretending the proposed
> fix was applied.

## Status — 2026-09-05

| # | Recommendation | Status |
| --- | --- | --- |
| **R1** | Declare and install `razorpay` — **P0** | ✅ **Closed.** `"razorpay>=1.4"` is in `pyproject.toml`; a real test-mode order, Checkout and signed webhook completed end to end on 2026-09-04 |
| **R2** | Render markdown in the chat transcript | ✅ **Closed by a different route (ADR-020).** No markdown renderer was added. The transcript is prose-only and every recommended product renders as a card in its own panel; system prompt 1.1.0 rules 13–16 forbid a table, a SKU list or an attribute dump in the reply. The defect was the *content*, and removing it beat rendering it |
| **R3** | Validate `GROQ_API_KEY` at startup | ⬜ **Open.** `groq_api_key` is still `SecretStr \| None = None` with no validator (`config.py:99`); a missing key still fails per turn rather than at boot |
| **R4** | Regenerate `PROGRESS.md` | ✅ **Closed 2026-09-05.** Regenerated from `PROJECT_STATE.md`; the false "Razorpay keys are `REPLACE_ME`" claim this recommendation named is gone |
| **R5** | Correct the four false documentation claims | ✅ **Closed.** All four corrected; `docs/notes/deviations.md` and `open-questions-status.md` carry the current positions |
| **R6** | Configure a git remote and merge the branch | ⬜ **Open.** `git remote -v` is still empty; CI has never run. Needs the owner's hosting decision |
| **R7** | Complete M11 live once R1 lands | ✅ **Closed 2026-09-04.** Order → Checkout → signed webhook → `PAYMENT_CONFIRMED` → audit, and the `payment.failed` path verified live too |
| **R8** | Warn when settings are stale | ⬜ **Open.** Startup logs `environment`, `version` and `merchant_id` (`main.py:48`) but no configuration fingerprint, so a stale process is still not identifiable from its logs |
| **R9** | Automate frontend E2E and cover responsive | ⬜ **Open, and now demonstrably the most valuable item on this list.** No Playwright. The 2026-09-05 browser walkthrough found **four** defects that 1,697 backend and 69 frontend tests all passed over — see `docs/notes/bugs-found-during-development.md` §A2. Every one needed a real browser in a real state |
| **R10** | Decide F9, then build the evaluation harness | ✅ **Closed.** F9 decided and `backend/tests/evals/` built: 270 cases, 3,470 deterministic checks, 268 passing. `docs/EVALUATION-REPORT.md` |
| R11 | Concurrent-order-submission test | ⬜ Open |
| R12 | Move `Turn` to a types module; retire `useChat.ts` | ⬜ Open |
| **R13** | Remove the orphan `anthropic` package | ✅ **Closed.** Not in `pyproject.toml` |
| **R14** | Delete the empty root `app/` directory | ✅ **Closed.** Removed in `c67186b` |

**Four open (R3, R6, R8, R9), plus two P2/P3 tidy-ups. None blocks the money path.** R9 is the one
that has since earned a promotion: it is the only item on this list whose absence has cost real
defects rather than tidiness.

---

## R1 — Declare and install the `razorpay` dependency · **P0 · BLOCKS THE PROJECT**

**Problem.** `razorpay` appears in neither `dependencies` nor `[project.optional-dependencies].dev`
in `backend/pyproject.toml`, and is not installed.

**Why it matters.** It is the only thing standing between this project and a fully verified money
path. Every other component in that path was proven live during this audit.

**Evidence.** `POST /api/orders/{id}/checkout` → `503 PAYMENT_PENDING: "the razorpay package is not
installed"`. Import check confirms absence; `pyproject.toml` inspection confirms it is undeclared.

**Fix.** Add `"razorpay>=1.4"` to `dependencies`, then `pip install -e ".[dev]"`.

**Complexity.** Trivial — one line. **Blocks:** M11, M14/F6, M15 payment scenarios.

---

## R2 — Render markdown in the chat transcript · P1 · does not block

**Problem.** Groq returns markdown tables and `**bold**`; `ChatWindow` renders plain text, so buyers
see literal pipes and asterisks.

**Why it matters.** It is the first thing anyone sees, and the most visible defect in the product.

**Evidence.** Browser screenshot: a full markdown table rendered as raw `| # | Product | … |` rows.

**Fix.** Render assistant prose through a markdown component. `@assistant-ui/react-markdown` is the
natural fit and the runtime is already present. Keep it to prose only — cards stay structured.

**Complexity.** Low. **Blocks:** nothing, but it gates any demo.

---

## R3 — Validate `GROQ_API_KEY` at startup · P1 · does not block

**Problem.** The key defaults to `None` and `from_settings` passes `api_key=""`, so a missing key
fails per-turn at call time instead of loudly at boot.

**Why it matters.** This exact class of failure already happened: the key lived only in one process's
memory and the application looked healthy. A restart would have broken every turn with an
authentication error rather than a configuration error.

**Evidence.** `config.py:96`, `client.py:149`; `Settings.groq_api_key` resolved `False` while the
running process still worked.

**Fix.** Add a validator requiring a non-empty key outside test runs — the same treatment
`GROQ_MODEL`, `DATABASE_URL` and `RANKING_PROFILE` already get. **Complexity.** Low.

---

## R4 — Regenerate `PROGRESS.md` · P1 · does not block

**Problem.** It names commit `38232ea` (six behind HEAD) and asserts Razorpay keys are `REPLACE_ME`,
which is false. `CLAUDE.md` explicitly forbids it contradicting `PROJECT_STATE.md`.

**Why it matters.** It actively misdirects: a reader would chase a credentials problem that does not
exist and never find the missing package.

**Fix.** Regenerate from `PROJECT_STATE.md`. Consider deriving it mechanically so it cannot drift
again. **Complexity.** Low.

---

## R5 — Correct the four false documentation claims · P2 · does not block

`sdk.py` docstring (blames `REPLACE_ME`), `open-questions-status.md` F4 ("no workflow exists"),
`CLAUDE.md` (a boundary guard test that does not exist), UX spec §0 (names Anthropic).

**Why it matters.** This project's documentation is unusually load-bearing — sessions are instructed
to trust the repository over recollection. A false claim there is more damaging than in most
codebases. **Complexity.** Low.

---

## R6 — Configure a git remote and merge the branch · P1 · does not block

**Problem.** No remote. CI has never run and cannot. Six commits — all Groq and frontend work — sit
unmerged on `m4r-groq-and-b14-frontend`; `main` has none of it.

**Why it matters.** The safety net exists and is switched off. The project's real state lives only on
a local feature branch.

**Fix.** Add a remote, push, open a PR, let CI run. **Complexity.** Low, but needs the owner's
decision about hosting.

---

## R7 — Complete M11 live once R1 lands · P1 · does not block

With the SDK present, create a real test-mode order, drive Razorpay Checkout in a browser, and let a
genuine `payment.captured` arrive through the existing ngrok tunnel. Credentials, tunnel and webhook
handling are already verified — only this step remains.

**Complexity.** Low-to-medium, mostly waiting. **Closes:** M11, M14/F6, most of M15.

---

## R8 — Add a warning when settings are stale · P1 · does not block

**Problem.** `@lru_cache(maxsize=1)` means a process serves start-up configuration forever with no
signal.

**Evidence.** During this audit the backend on 8001 rejected a correctly-signed webhook; a fresh
process on 8002 accepted the identical payload. That cost real diagnostic time.

**Fix.** Log a non-secret configuration fingerprint at startup (model name, environment, a hash of
secret *lengths* — never values) so a stale process is identifiable. **Complexity.** Low.

---

## R9 — Automate frontend E2E and cover responsive · P2 · does not block

Playwright against a seeded backend: the full journey plus three viewport widths. This audit's
browser verification was manual and therefore unrepeatable, and mobile was never confirmed at all.
**Complexity.** Medium.

---

## R10 — Decide F9, then build the evaluation harness · P2 · does not block

M15's "should-work" suite cannot be built until its format is chosen. It is the last substantive
piece of specified work that has not started. **Complexity.** Medium; the decision is the hard part.

---

## Lower priority

| # | Action | Priority |
| --- | --- | --- |
| R11 | Add a concurrent-order-submission test | P2 |
| R12 | Move `Turn` to a types module; retire `useChat.ts` | P3 |
| R13 | Remove the orphan `anthropic` package | P3 |
| R14 | Delete the empty root `app/` directory | P3 |
| R15 | Give `artifact-export.md` a stated role or remove it | P3 |
| R16 | Add `aria-describedby` on error associations | P3 |
| R17 | Free port 8000, or document the conflict more loudly | P3 |

---

# DO NOT CHANGE

These are correct. Changing them would cost quality and buy nothing.

### The Groq provider decision
**Locked and permanent** (ADR-018). Verified working, restart-safe, single import site. Do not
migrate, and do not "clean up" the architecture by replacing it.

### The ranking engine
Pure, deterministic, 136 tests, reproduces the specification's worked example to six decimal places.
Do not introduce a database call, a clock, randomness, or model involvement.

### `create_order` being absent as a tool
Not registered-and-guarded — **absent**, with four tests keeping it so. Do not add it "for
completeness".

### The money representation
`Decimal` and `NUMERIC(12,2)`, strings at the API, integer minor units confined to `app/payments/`.
Do not introduce a float anywhere.

### The policy engine's re-read
It re-reads price and stock **live inside the order transaction** and evaluates all ten rules. Live
price-drift rejection in both directions depends on this. Do not optimise it to use the cart
snapshot.

### Webhook verification
Raw body captured before parsing, HMAC-SHA256, constant-time compare, dedupe by UNIQUE constraint.
Do not add a Pydantic body model to that route — it would destroy the raw bytes.

### Application-issued idempotency keys
Rejecting client-invented keys is a real security property. Do not relax it.

### The test seams
`LLMClient` and `RazorpayApi` protocols look like indirection; they are what lets 164 tests run with
no credentials and no network. Do not collapse them.

### The Assistant UI scope
Runtime only, non-streaming adapter. Do not adopt its streaming or tool-call UI — the first would
reopen ADR-010, the second describes browser-executed tools this system does not have.

### The boundary guards
AST-walking tests that enforce architecture. Do not weaken them to make a refactor pass.
