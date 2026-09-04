# Engineering Audit — Merchant AI Commerce Agent

**Date:** 2026-09-03 · **Repository:** `L:\AI_COMMERCE` · **Branch:** `m4r-groq-and-m14-frontend`
**HEAD:** `4081628` · **Working tree:** clean at audit start

This audit verifies the repository against its own specification by inspecting source, querying the
database, exercising the HTTP API, driving a browser, and running every suite. Documentation claims
were treated as hypotheses and checked; several were found stale and are recorded as findings rather
than silently corrected.

## Verification vocabulary

The audit distinguishes five levels. A claim is only promoted when evidence exists for it.

| Level | Meaning |
| --- | --- |
| **IMPLEMENTED** | Source exists and compiles |
| **UNIT TESTED** | Covered by tests that use doubles, not the real dependency |
| **INTEGRATION TESTED** | Covered against a real database or a real in-process API |
| **RUNTIME VERIFIED** | Exercised against the live running application in this audit |
| **EXTERNALLY VERIFIED** | Exercised against the real third-party service |

## Index

| # | Document | Subject |
| --- | --- | --- |
| 01 | [project-overview](01-project-overview.md) | What the system is, and its invariant |
| 02 | [module-inventory](02-module-inventory.md) | Every module, status, tests, runtime state |
| 03 | [spec-vs-code](03-spec-vs-code.md) | Specification versus implementation, contradictions |
| 04 | [backend-audit](04-backend-audit.md) | Per-module backend audit |
| 05 | [database-audit](05-database-audit.md) | Schema, constraints, migrations, seed |
| 06 | [groq-audit](06-groq-audit.md) | The locked LLM provider |
| 07 | [ranking-audit](07-ranking-audit.md) | Deterministic ranking engine |
| 08 | [commerce-flow-audit](08-commerce-flow-audit.md) | Cart → approval → policy → order |
| 09 | [razorpay-audit](09-razorpay-audit.md) | Payments and webhooks |
| 10 | [api-audit](10-api-audit.md) | Every HTTP endpoint |
| 11 | [frontend-audit](11-frontend-audit.md) | React frontend and Assistant UI |
| 12 | [e2e-test-report](12-e2e-test-report.md) | The live end-to-end run |
| 13 | [test-audit](13-test-audit.md) | Suite results and coverage gaps |
| 14 | [security-audit](14-security-audit.md) | Secrets, money, trust boundaries |
| 15 | [code-quality](15-code-quality.md) | Debt, ranked P0–P3 |
| 16 | [application-examples](16-application-examples.md) | Seven worked scenarios |
| 17 | [gap-analysis](17-gap-analysis.md) | Complete gap matrix |
| 18 | [recommendations](18-recommendations.md) | What to do, and what not to touch |
| 19 | [final-readiness-report](19-final-readiness-report.md) | **Start here for the verdict** |

## Headline

The system is **91% complete** and architecturally sound. Its central invariant holds under
inspection: no path lets the model invent a price, a stock level or an order.

**One P0 blocker:** the `razorpay` Python package is neither installed nor declared in
`backend/pyproject.toml`. Payment execution therefore cannot run, and this — not missing credentials,
which are present and valid — is what has kept M11 unverified.

## Constraints honoured

Groq is treated throughout as the permanent, locked provider (ADR-018); no migration is proposed. No
credential value was printed or written to any file. No application source was modified and nothing
was committed. `L:\RazorPay\backend` was not inspected or referenced.
