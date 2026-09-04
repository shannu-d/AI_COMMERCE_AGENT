# 19 — Final Project Readiness Report

**Date:** 2026-09-03 · **Repository:** `L:\AI_COMMERCE` · **HEAD:** `4081628`
**Branch:** `m4r-groq-and-b14-frontend` (6 commits ahead of `main`, unmerged)

---

## 1. Executive summary

The Merchant AI Commerce Agent is a **well-engineered, architecturally disciplined system that is
substantially complete and now largely runtime-verified**. Its central invariant — *LLM proposes,
application validates, user authorizes, Razorpay executes, system audits* — holds under direct
inspection at every layer, enforced by AST-walking tests rather than convention.

This audit did not merely read the code. It ran the application, drove a browser, exercised every
endpoint, queried the live database, made real Groq calls, and executed the money path end to end.
**In doing so it created the first order this project has ever produced** and verified the flagship
price-drift guarantee live in both directions.

**One P0 blocker exists, and it is not what the documentation says it is.** The `razorpay` Python
package is neither installed nor declared in `pyproject.toml`. Two documents blame missing
credentials; the credentials are present, valid and test-mode. The fix is one dependency line.

Beyond that, findings are documentation drift, one visible presentation defect (raw markdown in the
chat), and verification gaps concentrated entirely at the third-party payment boundary.

---

## 2–5. Completion percentages

Classification: **COMPLETE** = implemented + tested + acceptance criteria verified · **PARTIAL** =
implemented, some criteria unverified · **BLOCKED** = implemented, verification needs an unavailable
dependency · **NOT STARTED** = absent.

Scoring: COMPLETE = 1.0, PARTIAL = 0.5, BLOCKED = 0.5, NOT STARTED = 0.

### Overall — **91%**

| Milestone | Status | Score |
| --- | --- | --- |
| M0 Foundation | COMPLETE | 1.0 |
| M1 Catalog schema + seed | COMPLETE | 1.0 |
| M2 Catalog read services | COMPLETE | 1.0 |
| M3 Ranking engine | COMPLETE | 1.0 |
| M4 LLM layer | COMPLETE | 1.0 |
| M4-R Groq provider | COMPLETE (externally verified) | 1.0 |
| M5 Agent runtime | COMPLETE | 1.0 |
| M6 Commerce schema | COMPLETE | 1.0 |
| M7 Cart | COMPLETE (runtime verified) | 1.0 |
| M8 Approval | COMPLETE (runtime verified) | 1.0 |
| M9 Policy engine | COMPLETE (runtime verified) | 1.0 |
| M10 Orders + idempotency | COMPLETE (runtime verified) | 1.0 |
| M11 Razorpay orders | **BLOCKED** — SDK absent | 0.5 |
| M12 Webhook | COMPLETE (runtime verified) | 1.0 |
| M13 Audit + trace | COMPLETE (runtime verified) | 1.0 |
| M14 Frontend | PARTIAL — F6 blocked, F9 partial | 0.5 |
| M15 Integration & evaluation | PARTIAL — backend done, no eval harness | 0.5 |

**Calculation:** (14 × 1.0) + (1 × 0.5) + (2 × 0.5) = **15.5 / 17 = 91.2% → 91%**

### Backend — **97%**
M0–M13 = 15 units. 14 COMPLETE, 1 BLOCKED (M11).
**(14 + 0.5) / 15 = 96.7% → 97%**

### Frontend — **90%**
Phases F0–F9 = 10 units. F0–F5, F7, F8 COMPLETE (8); F6 BLOCKED; F9 PARTIAL.
**(8 + 0.5 + 0.5) / 10 = 90%**
(F10+ storefront excluded — deliberately deferred, not in MVP scope.)

### Database — **100%**
20 tables, 36 FKs, 56 CHECK constraints, 57 indexes, 4 migrations, idempotent seed, round-trip
proven, model-to-migration drift caught offline. **No defects found at any level.**

---

## 6. LLM / Groq status — ✅ COMPLETE, EXTERNALLY VERIFIED

Provider is **Groq**, model `openai/gpt-oss-120b`, locked by ADR-018. One import site
(`app/llm/client.py`). **Zero executable Anthropic references** in `backend/app/` (AST-verified; all
14 textual hits are comments). Live calls succeed. **Restart-safety proven** by starting a fresh
backend from `.env` alone and completing a real turn.

Operational limit: free tier ≈ 8,000 tokens/minute ≈ one turn per two minutes.

## 7. Razorpay status — 🔴 BLOCKED (SDK), webhook ✅ VERIFIED

| Component | Status |
| --- | --- |
| Credentials (all three, test mode) | ✅ present and valid |
| Webhook signature verification | ✅ **runtime verified** — `400` tampered, `200` valid |
| Webhook deduplication | ✅ **runtime verified** — replay ignored |
| Money conversion (₹999.00 → 99900) | ✅ **runtime verified** |
| ngrok tunnel | ✅ running → `localhost:8001` |
| **Provider order creation** | 🔴 **BLOCKED — package absent** |
| **Payment capture** | 🔴 BLOCKED |

## 8. Test status — ✅ EXCELLENT

**1,334 passed · 0 failed · 0 skipped · 0 xfail.**
Backend 1,292 (with a real PostgreSQL, so `requires_db` tests actually ran). Frontend 42.
Typecheck clean, eslint clean, build succeeds. 16,766 lines of test against 15,433 of application.

## 9. E2E status — ✅ 17 of 19 checks passed

One failed: Razorpay checkout (`503`, SDK). One passed by a non-browser route (webhook).
**The first order in project history was created during this audit**, and price drift was rejected
live in both directions.

## 10. Security status — ✅ STRONG (one production gap)

No exploitable defect in the money path. Secrets properly typed, redacted, gitignored and absent from
the frontend. Webhook crypto correct. Injection contained by design — model output is a lookup key,
never a fact.
**Production gap:** there is no authentication at all (ADR-006 has no `users` table). Appropriate and
documented for the MVP; blocking for real deployment.

## 11. Documentation status — ⚠️ GOOD BUT DRIFTING

19 ADRs, indexed, no competing live decisions. `PROJECT_STATE.md` is **accurate** — its claims matched
the database and source exactly. But five documents carry false or contradictory claims, most
damagingly `PROGRESS.md`, which misattributes the P0 to credentials.

---

## 12. Critical blockers

| # | Blocker | Impact |
| --- | --- | --- |
| **1** | **`razorpay` neither installed nor declared** | Blocks M11, M14/F6, M15 payment scenarios — the entire external money path |

**That is the complete list.** One blocker.

## 13. High-priority issues (P1)

1. Raw markdown rendered in the chat transcript — the most visible product defect
2. Missing Groq key fails per-turn rather than at startup
3. `@lru_cache` settings served stale with no warning (caused a real misdiagnosis during this audit)
4. CI has never run — no git remote; 6 commits unmerged, `main` lacks all Groq and frontend work
5. `PROGRESS.md` stale and contradicting `PROJECT_STATE.md`
6. All payment tests use doubles — provider contract unproven (blocked by the P0)
7. No authentication (production-blocking, MVP-acceptable)

## 14. Medium and low issues

14 P2 (documentation contradictions, unverified responsive layouts, no eval harness, no concurrency
test, no automated frontend E2E) and 15 P3 (orphan `anthropic` package, superseded `useChat.ts`,
empty root `app/`, bundle size, `::1` binding). Full list in
[15-code-quality](15-code-quality.md).

## 15. What is already working

Everything except payment execution. Specifically **runtime-verified in this audit**: the full agent
turn against real Groq; deterministic ranking with correct tie-breaking; compatibility resolution;
inventory filtering with `LOW_STOCK`; cart with server-computed totals; approval with TTL and
supersession; the policy engine passing and failing; order creation with correct minor-unit
conversion; idempotent replay; **price-drift rejection in both directions**; webhook verification,
rejection and deduplication; and a complete audit trail.

## 16. What is only theoretically implemented

- Razorpay order creation — code complete, 17 tests, never executed
- Payment capture and failure state transitions — never correlated to a real provider order
- Frontend Razorpay Checkout (F6) — built, cannot run
- Order page polling to a terminal state — unit tested, never driven
- Responsive layouts — 8 breakpoint utilities, never verified at any width
- CI pipeline — written, never executed

## 17. What has actually been runtime tested

See §15. In addition: 11 API endpoints exercised with valid, invalid, malformed, duplicate and
unauthorized inputs; CORS confirmed; the browser journey from empty state through the approval
dialog; database schema and constraints read live; and Groq restart-safety proven on a fresh process.

## 18. What still requires manual testing

Razorpay Checkout in a browser · a real `payment.captured` correlating to a provider order ·
`payment.failed` state transition · mobile and tablet layouts · order-page polling to terminal ·
CI on a runner · concurrent order submission.

## 19. Recommended next milestone

**Complete M11 — the live Razorpay test-mode order.**

It is the only P0, everything around it is already verified, and closing it also closes M14/F6 and
most of M15's payment scenarios. It is the single highest-leverage action available.

## 20. Exact commands for the next step

```bash
# 1. Declare the missing dependency in backend/pyproject.toml
#    add to [project].dependencies:   "razorpay>=1.4",

cd L:\AI_COMMERCE\backend
pip install -e ".[dev]"
python -c "import razorpay; print('razorpay', razorpay.__version__)"

# 2. Restart the backend so it picks up current .env (settings are cached at startup)
python -m uvicorn app.main:app --host 127.0.0.1 --port 8001 --reload

# 3. Re-run the money path; checkout should now return a real razorpay_order_id
#    (chat -> cart -> approve -> order -> checkout)

# 4. Point the Razorpay dashboard webhook at the running tunnel
#    https://tiara-shaded-dutiful.ngrok-free.dev/api/webhooks/razorpay

# 5. Regression check
cd L:\AI_COMMERCE\backend
python -m pytest -q                       # expect 1292 passed, 0 skipped
cd ..\frontend && npm run test            # expect 42 passed
npx tsc --noEmit && npx eslint . --max-warnings 0 && npm run build
```

⚠️ **Use port 8001 or 8002, never 8000** — port 8000 is an unrelated application.
⚠️ **Use `localhost:5173`, not `127.0.0.1:5173`** — Vite binds to `::1`.

---

## Verdict

**91% complete, architecturally sound, and one dependency line away from a fully verified money
path.** The engineering quality is high: zero TODO markers, zero architecture violations, more test
code than application code, and safety properties enforced structurally rather than by convention.
The remaining work is small, well-understood, and concentrated in one place.
