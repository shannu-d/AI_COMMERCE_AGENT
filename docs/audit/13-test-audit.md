# 13 — Test Suite Audit

## Results

| Suite | Command | Passed | Failed | **Skipped** | xfail | Warnings |
| --- | --- | --- | --- | --- | --- | --- |
| Backend | `pytest -q -rs` | **1292** | 0 | **0** | 0 | none surfaced |
| Frontend | `vitest run` | **42** | 0 | **0** | 0 | none |
| **Total** | | **1334** | **0** | **0** | 0 | |

Run with `TEST_DATABASE_URL` pointed at PostgreSQL, so the `requires_db` tests **actually ran**. This
matters: those tests skip with a visible reason when the database is unreachable, and a run showing
skips is an incomplete run, not a pass. **Zero skips is the meaningful number here.**

| Static check | Result |
| --- | --- |
| `ruff check` / `ruff format` | configured; suite green |
| `tsc --noEmit` (strict) | CLEAN |
| `eslint --max-warnings 0` | CLEAN |
| `vite build` | 518.16 kB (gzip 153.08 kB) |

## Distribution

| Area | Tests | Notes |
| --- | --- | --- |
| `services` | 217 | largest suite |
| `llm` | 147 | all with **no key and no network** |
| `ranking` | 136 | includes the R§10 exit criterion |
| `agent` | 111 | boundary guards, executor ordering |
| `api` | 96 | includes 15 CORS, 5 frontend-contract |
| `db` | 88 | migrations, integrity, relationships |
| `policy` | 35 | per-rule coverage |
| `seed` | 32 | includes validate-only |
| `payments` | 17 | **all against doubles** |
| `integration` | 12 | named end-to-end scenarios |
| Frontend | 42 | 7 covering the Assistant UI runtime |

**16,766 lines of backend test code against 15,433 lines of application code** — more test than
application.

## Coverage and gap matrix

| Area | Unit | Integration | Runtime | External | Gap |
| --- | --- | --- | --- | --- | --- |
| Configuration | ✅ | ✅ | ✅ | n/a | — |
| Domain / enums | ✅ | ✅ | ✅ | n/a | — |
| Migrations | ✅ | ✅ | ✅ | n/a | — |
| Seed | ✅ | ✅ | ✅ | n/a | — |
| Catalog / compatibility / inventory | ✅ | ✅ | ✅ | n/a | — |
| Ranking | ✅ | ✅ | ✅ | n/a | — |
| LLM layer | ✅ | ✅ | ✅ | ✅ Groq | — |
| Agent runtime | ✅ | ✅ | ✅ | ✅ | — |
| Cart | ✅ | ✅ | ✅ | n/a | — |
| Approval | ✅ | ✅ | ✅ | n/a | — |
| Policy engine | ✅ | ✅ | ✅ | n/a | — |
| Orders / idempotency | ✅ | ✅ | ✅ | n/a | — |
| Price drift (both directions) | ✅ | ✅ | ✅ | n/a | — |
| Webhook verify / dedupe | ✅ | ✅ | ✅ | ⚠️ synthetic | Never a **real Razorpay-signed** event |
| Money conversion | ✅ | ✅ | ✅ | n/a | — |
| **Razorpay order creation** | ✅ doubles | ❌ | ❌ | ❌ | 🔴 **SDK absent** |
| **Payment capture → order state** | ✅ doubles | ⚠️ | ❌ | ❌ | 🔴 blocked |
| Frontend components | ✅ | ✅ | ✅ | n/a | — |
| Assistant UI runtime | ✅ | ✅ | ✅ | n/a | — |
| Frontend checkout (F6) | ⚠️ | ❌ | ❌ | ❌ | 🔴 blocked |
| Order page polling | ✅ | ❌ | ❌ | n/a | Never driven |
| Responsive layouts | ❌ | ❌ | ❌ | n/a | Never visually verified |
| **Evaluation harness** | ❌ | ❌ | ❌ | n/a | 🔴 **does not exist** |

## Test quality assessment

**Strengths — unusually good.**

- **Boundary guards are AST-based, not text greps.** They walk the syntax tree to prove the
  deterministic packages never import the model layer and that only one module imports the provider
  SDK. These cannot be fooled by a comment.
- **The model is faked at the protocol, never at the network.** All 147 LLM tests run with no key.
  SDK doubles raise the SDK's *real* exception classes, because error mapping dispatches on class
  identity — a double raising a generic `Exception` would pass while the production path failed.
- **Tests encode reasoning, not just behaviour.** `test_a_cheaper_incompatible_product_is_never_a_candidate`
  states a business rule. `test_an_internal_failure_never_narrows_onto_a_business_code` states a
  safety property.
- **Cross-language contract enforcement.** A backend test fails the build if the frontend's error-code
  list diverges, or if a secret-bearing name appears in frontend source.
- **The exit criterion is exact.** `Decimal("0.796800")` against the specification's `0.7968`.
- **Migration drift is caught offline.** DDL is diffed against model metadata, constraint names
  included, with no database required.

**Weaknesses.**

| # | Weakness | Severity |
| --- | --- | --- |
| 1 | **No evaluation harness** (M15 / F9) — the "should-work" scenario suite the specification asks for does not exist; its format was never decided | P2 |
| 2 | All 17 payment tests use doubles; nothing has ever exercised the real provider | P1 (blocked by P0) |
| 3 | Webhook tests use self-generated signatures, never a genuine Razorpay-signed delivery | P2 |
| 4 | No frontend E2E automation — the browser run was manual | P2 |
| 5 | Responsive breakpoints have no test at all | P2 |
| 6 | `OrderPage` polling has unit tests but was never driven to a terminal state | P2 |
| 7 | **CI has never run** — the workflow exists but no git remote is configured | P1 |

## Tests that only assert implementation details

Very few. The prompt tests are explicitly scoped to *auditability* — that every prompt file has a
version entry — rather than to model behaviour, which is the right call: per L§29 and ADR-009, prompt
wording makes the agent behave well and is not what stops it behaving badly. That distinction is
stated in the code and honoured in the tests.

## Verdict

**The test suite is a genuine strength of this project.** 1,334 tests, zero skips, zero failures, and
the guards enforce architecture rather than merely exercising code. The gaps are concentrated in
exactly one place — the third-party payment boundary — plus a missing evaluation harness.
