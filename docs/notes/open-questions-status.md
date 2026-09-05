# Open Questions — Verified Status

**Date:** 2026-08-31
**Method:** every entry in [`../analysis/03-open-questions.md`](../analysis/03-open-questions.md)
was checked against the actual contents of `docs/decisions/` and the shipped code, not against the
previous session's report.

Legend: **CLOSED** — decided in an ADR and, where in scope, implemented.
**DEFERRED** — decided *not* to do it now, with the reason recorded.
**OPEN** — genuinely unresolved. The milestone it blocks is named.

---

## Project-level items

### U1 — Sole project root. **CLOSED.**

`L:\AI_COMMERCE` is the only project root. All source code, documentation, migrations, tests and
configuration for this project live under it.

`L:\RazorPay\backend` is a **separate, unrelated project**. It must not be inspected, copied,
imported, merged, referenced, or depended on. It was noted in the Phase 0 assessment only so it
would not later be mistaken for a prior state of this repository.

Verified on 2026-08-31: `grep -rIn "RazorPay\\backend|L:\\RazorPay" .` returns **no matches in any
source file, test, migration or configuration file**. The only occurrences are in documentation, and
every one of them is an instruction not to use it.

This rule is recorded in `CLAUDE.md` so future sessions inherit it.

### U2 — External project brief. **OPEN, external-input gap. Blocks nothing.**

Fully documented in [`external-brief-gap.md`](external-brief-gap.md): what is referenced, what was
searched, the six brief-derived requirements the supplied documents actually state, why
implementation proceeds, and what to compare if the brief arrives.

### U3 — PostgreSQL provisioning on this machine. **CLOSED in practice.**

No Docker and no installed PostgreSQL. A throwaway PostgreSQL 16.4 is provisioned in the session
scratchpad from the official Windows binary archive — `initdb` plus `pg_ctl`, user space, no service.
The full suite runs against it. `docker-compose.yml` remains the supported path for any machine with
Docker.

---

## A — Ranking and recommendation

| ID | Question | Status |
| --- | --- | --- |
| A1 | Two competing weight sets | **CLOSED** — ADR-004 |
| A2 | RelevanceScore formula | **CLOSED** — ADR-004 |
| A3 | PriceScore with no budget | **CLOSED** — ADR-004 |
| A4 | PreferenceScore with no preferences | **CLOSED** — ADR-004 (`0.0`) |
| A5 | Multi-product budget combination | **CLOSED** — ADR-004 |
| A6 | Top-K scope | **CLOSED** — ADR-004 (per product type) |
| A7 | Who writes the recommendation reason | **CLOSED** — ADR-004, ADR-010 (the ranker) |
| A8 | Dynamic intent-driven weighting | **DEFERRED** — ADR-004; named profiles instead |

## B — Catalog and compatibility

| ID | Question | Status |
| --- | --- | --- |
| B1 | Device-identifier canonicalization | **CLOSED** — ADR-003; table + seed shipped in M1, resolver in M2 |
| B2 | Category slugs not shared with the model | **CLOSED** — ADR-009 (enum in the tool schema) |
| B3 | `constraints` JSONB semantics | **CLOSED** — ADR-003 (predicates on the product's own attributes) |
| B4 | `rule_type` enum | **CLOSED** — ADR-003 (`compatible` only, CHECK-enforced) |
| B5 | Product-level compatibility vs variant-level price/stock | **CLOSED** — ADR-003 accepts product-level for the MVP; limitation recorded |
| B6 | Product images missing from the schema | **DEFERRED** — `deviations.md` F3; a column plus a migration when M14 needs it |
| B7 | `search_catalog` product/variant granularity | **CLOSED** — ADR-009 (one row per variant) |
| B8 | Merchant scoping at runtime | **CLOSED** — ADR-002; `DEFAULT_MERCHANT_ID` config, enforced by composite FKs |
| B9 | Currency handling | **CLOSED** — ADR-002, ADR-008 (INR only, mismatch is an error) |

## C — Commerce schema and state

| ID | Question | Status |
| --- | --- | --- |
| C1 | Phase-2 tables have no columns | **CLOSED** — ADR-006 (all eleven, column level). Implemented in M6. |
| C2 | No user/identity model | **CLOSED** — ADR-006 (session-only identity) |
| C3 | Session and approval persistence | **CLOSED** — ADR-006, ADR-007 (PostgreSQL); `sessions` and `session_messages` implemented in M5, approvals still M8 |
| C4 | Money representation | **CLOSED** — ADR-008; catalog half shipped in M1 |
| C5 | `reserved_quantity` lifecycle | **DEFERRED** — ADR-005; stays `0`, race closed by a row lock in ADR-011 |
| C6 | Concurrency between policy check and order creation | **CLOSED** — ADR-011 (one transaction, `SELECT ... FOR UPDATE`) |
| C7 | Two overlapping state machines | **CLOSED** — ADR-006, ADR-007 (three separate enums) |

## D — Policy and payments

| ID | Question | Status |
| --- | --- | --- |
| D1 | Approval TTL | **CLOSED** — ADR-007 (15 minutes) |
| D2 | Price *decrease* handling | **CLOSED** — ADR-014 (fails in both directions) |
| D3 | Spending-limit scope | **CLOSED** — ADR-011 (per transaction, config) |
| D4 | Idempotency key minting, scope, TTL | **CLOSED** — ADR-013 |
| D5 | `request_approval` semantics | **CLOSED** — ADR-007, ADR-009 |
| D6 | Is `create_order` exposed to the model | **CLOSED** — ADR-009 (not registered at all); asserted four ways against the M5 registry |
| D7 | Which webhook events to subscribe | **CLOSED** — ADR-012 |
| D8 | Payment-failure recovery | **CLOSED** — ADR-012 (same path as price drift) |
| D9 | Price change while Checkout is open | **CLOSED** — ADR-014 (Razorpay amount final at creation) |
| D10 | Refunds and cancellation | **DEFERRED** — `deviations.md` F5; state exists, no transition |

## E — Agent, LLM and API

| ID | Question | Status |
| --- | --- | --- |
| E1 | Tool-call loop limit | **CLOSED** — ADR-009 (8 per turn); enforced in `app/agent/executor.py` from M5 |
| E2 | LLM retry / timeout values | **CLOSED** — ADR-015. Confirmed at M4 against the built client: 60s timeout, 2 retries, `0.5 × 2ⁿ` backoff, transient failures only, and the SDK's own retry loop disabled so the policy is bounded once rather than twice. |
| E3 | Two `/api/chat` response shapes | **CLOSED** — ADR-010; the union shape is served and tested from M5 |
| E4 | Tool naming inconsistency | **CLOSED** — ADR-009 (`search_catalog`) |
| E5 | Stock disclosure granularity | **CLOSED** — ADR-009, ADR-010 (coarse `stock_status` to the buyer) |
| E6 | Agent trace persistence | **CLOSED** — ADR-010 (per turn, not persisted) |
| E7 | `audit_events` schema | **CLOSED** — ADR-006 |

## F — Absent from the specification entirely

| ID | Gap | Status |
| --- | --- | --- |
| F1 | **LLM test-double strategy** | **CLOSED** — ADR-015, implemented in M4. The seam is the one-method `LLMClient` protocol; the model is faked at that protocol by `tests/llm/conftest.py::FakeClient`, and the SDK is faked only inside `tests/llm/test_client.py`. No test calls a live model at any milestone, and one AST-walking test holds `app/llm/client.py` as the sole importer of the SDK. Recorded cassettes were considered and rejected. |
| F2 | Test framework and DB fixture strategy | **CLOSED by implementation** — pytest, `requires_db` marker, transactional fixtures against a real PostgreSQL |
| F3 | Local dev orchestration | **CLOSED by implementation** — `docker-compose.yml`, plus the scratchpad fallback in U3 |
| F4 | CI pipeline | **OPEN. Blocks nothing; slows everything.** No workflow exists. Lint, format, type-check and the full suite all run locally in one command each, so a workflow is mechanical whenever it is wanted. |
| F5 | Deployment / hosting | **OPEN, out of scope.** Local only for the MVP. |
| F6 | Frontend framework (React vs Next.js) | **CLOSED** — ADR-017. **Vite**, not Next.js. The deciding fact is that `RazorpayClient.checkout_config()` returns only the *public* key ID, amount, currency and provider order ID, so the frontend holds no secret and the server layer Next.js supplies would protect nothing; with no SEO or SSR requirement either, F§3's "keep the frontend small" settles it. Supersedes `PROGRESS.md`'s earlier Next.js recommendation, which was written before `checkout_config()` was read. |
| F7 | Streaming responses | **CLOSED** — ADR-010 (no streaming; F§28 discourages it) |
| F8 | Non-functional targets | **OPEN, out of scope.** None set; agent turns will take seconds. |
| F9 | Evaluation harness format | **CLOSED 2026-09-04.** A generated JSON dataset (`backend/tests/evals/commerce_eval_cases.json`) plus a check registry (`graders.py`). The dataset is generated from the seeded catalogue and names no price, stock level or winning product; the answers are read from the database at run time. See `backend/tests/evals/README.md` and `docs/EVALUATION-REPORT.md`. |
| F10 | Accessibility / i18n | **OPEN, out of scope.** INR and English only. |
| F11 | The external brief | **OPEN** — see U2 and [`external-brief-gap.md`](external-brief-gap.md) |
| F12 | The CircuitCraft catalog data | **CLOSED by authoring** — ADR-002; 32 SKUs shipped in M1 under a no-fabricated-claims rule |

---

## What is open, and what it blocks

> **Provider question, settled by owner decision (2026-09-02).** The LLM provider is **Groq**,
> locked, per [ADR-018](../decisions/ADR-018-groq-as-the-locked-llm-provider.md), which supersedes
> ADR-016. Any statement elsewhere in this file or in `architecture.md` naming Anthropic or Claude
> as the provider is superseded. **Implemented and live-verified** (M4-R): model
> `openai/gpt-oss-120b`, an open-weights model served by Groq.


Five items remain open, and **none of them blocks anything.** F6 is closed by ADR-017, which also
added the CORS middleware that was blocking every frontend of every scope. F9 - the last item
that blocked anything reached - was closed on 2026-09-04 by the M15 evaluation suite.

| Open item | Blocks | Needed by |
| --- | --- | --- |
| F4 CI pipeline | nothing | whenever wanted |
| U2 / F11 external brief | nothing | external input; see the gap note |
| F5, F8, F10 | nothing | out of MVP scope |

F1 and E2 are closed by ADR-015. E3's union `/api/chat` contract was decided in ADR-010 and is
**built and tested as of M5**, along with the eight other questions the runtime turns from decisions
into code: A7 (the ranker writes the reason), B2 (category slugs are a schema enum), B7 (one row per
variant), C3 (sessions in PostgreSQL), C7 (three separate state machines), D6 (`create_order` is not
registered at all), E1 (eight tool calls per turn), E4 (`search_catalog` is the name), E5 (coarse
stock to the buyer) and E6 (the trace is per turn and not persisted).

The next thing owed is neither a decision nor a blocker: **M6**, the remaining nine commerce tables
of ADR-006. Its prerequisites — M1's schema foundation — have been complete since the first
milestone.
