# 17 — Gap Analysis

> **This is the gap analysis as written on 2026-09-03 and is not rewritten.** Where each gap stands
> now is the table immediately below; the original assessment follows unaltered.

## Status — 2026-09-05

| Gap | Then | Now |
| --- | --- | --- |
| Payment SDK (**P0**) | Neither installed nor declared | ✅ **Closed.** Declared, and the money path ran live end to end on 2026-09-04 |
| Checkout endpoint (**P0**) | `503 PAYMENT_PENDING` | ✅ **Closed.** Real provider orders; a signed `payment.captured` reached `PAYMENT_CONFIRMED` |
| Evaluation harness (P2) | Absent | ✅ **Closed.** `backend/tests/evals/` — 270 cases, 268 passing |
| Storefront pages (P3, deferred) | Chat-only product | ✅ **Built.** Home, category, product, cart, order, account and a seven-page merchant dashboard (M16, ADR-021/022/023) |
| Markdown rendering (**P1**) | Raw markdown shown | ✅ **Closed by removal, not rendering (ADR-020).** The transcript is prose-only; products render as cards in their own panel and the prompt forbids tables outright |
| Startup key validation (P1) | Silent, fails per turn | ⬜ **Still open** (audit R3) |
| Config freshness (P1) | `@lru_cache` serves start-up values forever | ⬜ **Still open** (audit R8) |

### One category this analysis did not have

**C. Defects only a browser in a real state can see.** The audit's own browser pass was manual and
therefore shallow; the 2026-09-05 walkthrough went through the whole buyer journey and found four
defects — a permanently disabled *Add to cart*, every agent turn failing on a per-minute token
bucket, a completed turn discarded by the browser's schema, and a buyer's order landing in no
account at all. Each passed 1,697 backend and 69 frontend tests. See
`docs/notes/bugs-found-during-development.md` §A2. This is what makes audit **R9** (automated E2E)
the most valuable open item on that list, rather than the P2 it was filed as.

## A. Missing implementation

| Area | Expected | Actual | Gap | Severity | Fix |
| --- | --- | --- | --- | --- | --- |
| Payment SDK | `razorpay` available | Neither installed nor declared | Payment execution impossible | **P0** | Declare in `pyproject.toml`, reinstall |
| Evaluation harness | M15 "should-work" suite | Absent | No systematic scenario evaluation | P2 | Decide F9 format, then build |
| Storefront pages | §5 home / listing / detail / history | Absent | Chat-only product | P3 (deferred) | Needs catalog endpoints — owner's decision |
| Markdown rendering | Readable assistant prose | Raw markdown shown | Visible product defect | **P1** | Render markdown in `ChatWindow` |
| Startup key validation | Loud failure on missing key | Silent, fails per turn | Misconfiguration looks healthy | P1 | Validate outside test runs |

## B. Broken implementation

| Area | Expected | Actual | Gap | Severity | Fix |
| --- | --- | --- | --- | --- | --- |
| Checkout endpoint | Creates a provider order | `503 PAYMENT_PENDING` | Money path stops | **P0** | Same as A/P0 |
| Config freshness | Process reflects `.env` | `@lru_cache` serves start-up values forever, silently | Confusing stale-secret failures | P1 | Log config fingerprint at startup |

**No logic defects were found.** Every failure above is environmental or presentational.

## C. Missing tests

| Area | Expected | Actual | Gap | Severity | Fix |
| --- | --- | --- | --- | --- | --- |
| Razorpay integration | Real provider exercised | 17 tests, all doubles | Provider contract unproven | P1 (blocked by P0) | Live test-mode order once unblocked |
| Webhook authenticity | A genuine Razorpay-signed delivery | Self-generated signatures only | Their signing scheme assumed | P2 | One real test-mode event |
| Concurrency | Simultaneous orders for one cart | None | Race unproven | P2 | Add a concurrent-submission test |
| Responsive | Layout at 3 widths | None | Untested and unverified | P2 | Playwright or manual pass |
| Frontend E2E | Automated journey | Manual browser run only | Regressions can slip | P2 | Playwright against a seeded backend |
| Order page | Polling to terminal state | Unit tests only | Never driven | P2 | Include in the E2E |

## D. Missing runtime verification

| Area | Status after this audit |
| --- | --- |
| Chat → recommendations | ✅ **now verified** |
| Cart → approval → order | ✅ **now verified (first order ever created)** |
| Idempotency replay | ✅ **now verified** |
| Price drift, both directions | ✅ **now verified** |
| Policy pass and fail | ✅ **now verified** |
| Webhook 400 / 200 / ignored | ✅ **now verified** |
| Audit trail | ✅ **now verified** |
| Groq restart-safety | ✅ **now verified** |
| Razorpay order creation | 🔴 still blocked |
| Razorpay Checkout in browser | 🔴 still blocked |
| Payment capture transition | 🔴 still blocked |
| Mobile / tablet rendering | ❌ still unverified |
| CI on a runner | ❌ still unverified |

## E. Documentation problems

| # | Problem | Severity | Fix |
| --- | --- | --- | --- |
| E1 | `PROGRESS.md` stale — wrong commit, false Razorpay claim; contradicts `PROJECT_STATE.md` against `CLAUDE.md`'s explicit rule | P1 | Regenerate |
| E2 | `sdk.py` docstring blames a `REPLACE_ME` secret that is actually valid | P2 | Correct to name the missing package |
| E3 | `open-questions-status.md` says no CI workflow exists; one does | P2 | Update F4 |
| E4 | `CLAUDE.md` claims a boundary guard test that does not exist | P2 | Soften the claim or write the test |
| E5 | UX spec §0 names Anthropic as provider | P2 | Correct to Groq per ADR-018 |
| E6 | `PROJECT_STATE.md` M11 blocker attributed to credentials | P2 | Re-attribute to the SDK |
| E7 | `artifact-export.md` has no stated role | P3 | Give it one or remove it |

**`PROJECT_STATE.md` is otherwise accurate** — its milestone claims matched the database and source
exactly, which is why it deserves its status as the canonical current-state document.

## F. Infrastructure blockers

| # | Blocker | Severity | Note |
| --- | --- | --- | --- |
| F1 | `razorpay` undeclared | **P0** | The one true blocker |
| F2 | No git remote — CI cannot run; 6 commits unmerged on a feature branch | P1 | `main` lacks all Groq and frontend work |
| F3 | Port 8000 occupied by an unrelated app answering `/api/health` | P2 | Misleads diagnosis |
| F4 | Groq free tier ≈ 1 turn / 2 minutes | P3 | Slows manual testing |
| F5 | No Docker or installed PostgreSQL — a throwaway instance is used | P3 | Documented workaround |
| F6 | Vite binds `::1`; `127.0.0.1:5173` fails | P3 | Use `localhost` |

## G. UX problems

| # | Problem | Severity |
| --- | --- | --- |
| G1 | Raw markdown in assistant messages | **P1** |
| G2 | Responsive unverified, and thin (8 utilities) | P2 |
| G3 | No product detail view (deliberate — no endpoint) | P3 |
| G4 | No product images (absent from the contract; not fabricated — correct) | P3 |
| G5 | No `aria-describedby` on error associations | P3 |

## H. Security concerns

| # | Concern | Severity | Note |
| --- | --- | --- | --- |
| H1 | Groq key existed only in process memory | **RESOLVED** this session | Now on disk, restart-verified |
| H2 | No authentication at all | P1 **for production**, P3 for the MVP | ADR-006 has no `users` table; session id is the only capability |
| H3 | No rate limiting on session creation | P2 for production | |
| H4 | `extra="ignore"` hides misspelled config | P2 | Caused H1 to go unnoticed |
| H5 | `anthropic` orphan dependency | P3 | Unnecessary supply-chain surface |

**No exploitable defect was found in the money path.** Every control tested held, including live
price-drift rejection in both directions.

## I. Technical debt

Full ranked list in [15-code-quality](15-code-quality.md). Summary: **0 P0 code-quality issues**
(the single P0 is a dependency declaration), 5 P1, 8 P2, 9 P3. Zero TODO/FIXME markers, zero
architecture violations.

## Gap summary by severity

| Severity | Count | Character |
| --- | --- | --- |
| **P0** | **1** | One missing dependency declaration |
| P1 | 8 | Presentation, config ergonomics, CI, doc drift |
| P2 | 14 | Test and verification gaps, documentation contradictions |
| P3 | 15 | Cosmetic, deferred, or environmental |

**The distribution is the finding.** A single P0, no architectural violations, and no logic defects —
in a system whose specification runs to 16,736 lines.
