# 15 — Code Quality / Technical Debt

## Headline metrics

| Metric | Value | Assessment |
| --- | --- | --- |
| TODO / FIXME / HACK / XXX | **0** across backend and frontend | Exceptional |
| Test-to-code ratio | 16,766 : 15,433 lines | Exceptional |
| Lint (ruff, eslint) | clean | |
| Typecheck (strict) | clean | |
| ADRs | 19, indexed, no two live decisions on one question | Exceptional |
| Dead configuration | 4 variables (**resolved this session**) | |

Finding zero TODO markers in a 15,000-line codebase is rare and reflects a real discipline: open
questions live in `docs/analysis/03-open-questions.md` and unresolved decisions become ADRs, rather
than accumulating as comments.

---

## P0 — Critical

### P0-1 · `razorpay` is neither installed nor declared
`backend/pyproject.toml` lists it in **neither** `dependencies` **nor**
`[project.optional-dependencies].dev`. A fresh clone plus the documented install cannot reach the
payment provider. Live checkout returns `503 PAYMENT_PENDING`.

**Blocks:** M11, M14/F6, M15's payment scenarios, the entire externally-verified money path.
**Fix:** one dependency line, then reinstall.

---

## P1 — High

### P1-1 · Assistant prose renders as raw markdown
Groq returns markdown tables and `**bold**`; `ChatWindow` renders plain text, so buyers see literal
pipes and asterisks. Observed in the browser. **The most visible user-facing defect in the product.**

### P1-2 · A missing Groq key fails per-turn, not at startup
`groq_api_key` defaults to `None` and `from_settings` passes `api_key=""`. Inconsistent with
`GROQ_MODEL`, `DATABASE_URL` and `RANKING_PROFILE`, all of which fail loudly at startup. A
misconfigured deployment looks healthy and breaks on every buyer message.

### P1-3 · Settings are cached with no staleness signal
`@lru_cache(maxsize=1)` means a running process serves configuration from start-up forever. This
caused a real, confusing failure during the audit: port 8001 rejected a correctly-signed webhook
because `.env` had changed under it. Nothing warns.

### P1-4 · CI has never run and cannot
`.github/workflows/ci.yml` exists (4,835 bytes) but **no git remote is configured**. Six commits sit
unmerged on `m4r-groq-and-b14-frontend`; `main` contains none of the Groq or frontend work.

### P1-5 · `PROGRESS.md` is stale and contradicts `PROJECT_STATE.md`
`CLAUDE.md` forbids this explicitly. It names commit `38232ea` (6 behind HEAD) and asserts Razorpay
keys are `REPLACE_ME`, which is false. A reader would misdiagnose the P0 as a credentials problem.

---

## P2 — Medium

### P2-1 · `app/payments/sdk.py` docstring asserts a false fact
Lines 8–10 claim the key is `REPLACE_ME`. The module raising the real error is itself misdescribing
the cause.

### P2-2 · `open-questions-status.md` contradicts `PROJECT_STATE.md` on CI
Line 119: "No workflow exists." One does.

### P2-3 · `CLAUDE.md` overstates a boundary guard
Claims a standing test asserts `app/agent/` is the only package importing both sides. **No such test
exists**, and `app/api/routes/chat.py:35` also imports both (legitimately, as a composition root).

### P2-4 · UX specification names the wrong provider
`docs/frontend/00-…md` §0 still says Anthropic. Superseded by ADR-018; flagged in the learning notes
but never fixed at source.

### P2-5 · No evaluation harness
M15's "should-work" scenario suite does not exist; open question F9 (its format) was never decided.

### P2-6 · Responsive layouts untested and thin
Eight breakpoint utilities across three files, and no test or visual verification at any width.

### P2-7 · Concurrency never forced
No test submits two orders for one cart simultaneously. Constraints make the outcome predictable, but
it is unproven.

### P2-8 · `PATCH`/`DELETE` cart endpoints never exercised at runtime
Tested, never driven.

---

## P3 — Low

| # | Issue |
| --- | --- |
| P3-1 | `anthropic` SDK installed but undeclared — orphan dependency, unnecessary surface |
| P3-2 | `features/chat/useChat.ts` superseded by the Assistant UI runtime; retained only for the `Turn` type, which belongs in a types module |
| P3-3 | Empty untracked `app/` directory at the repository root — confusable with `backend/app` |
| P3-4 | Bundle +80% (287 → 518 kB) for library features this architecture cannot use |
| P3-5 | 14 Anthropic references in `backend/app/` comments — all correct and explanatory, but a reader may misread them |
| P3-6 | No `aria-describedby` associating error text with controls |
| P3-7 | Two error envelope shapes (FastAPI 422 vs business `detail` object) — handled but undocumented |
| P3-8 | `artifact-export.md` at the repository root is an undated analysis export with no stated role |
| P3-9 | Vite binds to `::1`, so `127.0.0.1:5173` fails while `localhost:5173` works — a recurring time-waster |

---

## Architecture violations

**None found.** Every structural rule the project sets for itself holds under AST inspection:
deterministic packages import no model code, one module imports each provider SDK, ranking is pure,
no tool accepts a price, `create_order` does not exist as a tool.

The only inaccuracy is a *documentation* overstatement (P2-3), not a code violation.

## Duplicated code

None significant. `app/attributes.py` is deliberately the single implementation of "attribute
satisfies expectation", shared by three consumers that would otherwise each grow their own.

## Incorrect abstractions

None found. Two are worth defending explicitly because they look like over-engineering and are not:

- **The `RazorpayApi` two-method protocol** looks like indirection for its own sake. It is what lets
  17 payment tests run with no credentials and no HTTP.
- **Provider-agnostic transport types in `app/llm/models.py`** look unnecessary under a locked
  provider. They are why the Groq switch touched one concrete class rather than the whole layer.

## Overall

**High quality.** The debt is concentrated in documentation drift and one missing dependency
declaration — not in the design, which is unusually disciplined.
