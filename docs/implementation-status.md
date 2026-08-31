# Implementation Status Assessment

**Date:** 2026-08-30
**Scope of this document:** Phase 0 — inspection only. No application code existed when this
assessment was written, and no source document was modified to produce it.

---

## 1. Existing repository structure

`L:\AI_COMMERCE` before any implementation work:

```
AI_COMMERCE/
├── architecture.md                  199,499 bytes — the specification (six parts, 16,737 lines)
├── artifact-export.md                31,909 bytes — a Markdown export of a prior analysis artifact
└── docs/
    └── analysis/
        ├── README.md                  3,981 bytes
        ├── 01-architecture-inventory.md  16,968 bytes
        ├── 02-dependency-map.md          9,615 bytes
        ├── 03-open-questions.md         17,082 bytes
        ├── 04-task-breakdown.md         16,402 bytes
        └── 05-proposed-repo-structure.md 13,975 bytes
```

There is **no** `backend/`, `frontend/`, `src/`, `tests/`, `migrations/`, or configuration file of
any kind. The directory is also **not a Git repository**.

### Source documents that were expected but do not exist

| Expected document | Status |
| --- | --- |
| `architecture.md` | **Present.** Read in full. Treated as the specification. |
| `artifact-export.md` | **Present.** Read in full. See §8 — it is derived analysis, not a second spec. |
| `Design Product Catalog Database.txt` | **Absent.** Searched `L:\` to depth 4 and by filename pattern; no such file exists anywhere on the drive. |
| `README.md` | **Absent.** |

**Consequence:** the catalog design referred to as *"Design Product Catalog Database.txt"* is the
**PostgreSQL Database Architecture** part of `architecture.md` (§§1–41, lines 1715–4589). That part
specifies all seven Phase-1 tables at column level, with types, primary keys, foreign keys, unique
constraints and indexes. M1 is therefore implemented from that section, and this is recorded as an
identified-source substitution rather than a missing input.

### An unrelated prototype exists outside this repository

`L:\RazorPay\backend` contains a separate, previously-written FastAPI application (agent, policy,
services, routes, tests) backed by a **SQLite** file, `merchant_commerce.db`. It is outside the
project working directory, is not referenced by any source document, and uses a database engine
that contradicts the specification. **It has not been read into, copied from, or used by this
implementation.** It is noted here only so that it is not mistaken later for a prior state of this
repository. If it is meant to be the project's real starting point, that is a decision the project
owner must make explicitly — see §9, U1.

## 2. Existing code

**None.** Zero lines of application code, zero configuration files, zero scripts.

## 3. Existing database, schema, or migrations

**None.** No SQL, no ORM models, no Alembic environment, no migration versions, no seed data.

## 4. Existing tests

**None.** No test framework, no test files, no fixtures, no CI configuration.

## 5. Existing environment and configuration

**None committed.** There is no `.env`, `.env.example`, `pyproject.toml`, `requirements.txt`,
`docker-compose.yml`, or `.gitignore`.

Toolchain actually available on this machine (verified, not assumed):

| Tool | Status |
| --- | --- |
| Python | **3.14.7** — present |
| pip | 26.2.1 — present, with network access to PyPI (verified by a real download) |
| Git | 2.53.0 — present, but `L:\AI_COMMERCE` is not yet a repository |
| Node.js | 25.9.0 — present |
| Docker / Docker Compose | **Absent** |
| PostgreSQL server | **Absent** — no service, no install directory, nothing listening on 127.0.0.1:5432 |
| `psql` client | **Absent** |

**This is the single most important environmental fact in this assessment.** The specification
requires PostgreSQL (D§2, D§38) and the schema depends on PostgreSQL-only types — `UUID`, `JSONB`,
`TEXT[]`. There is no PostgreSQL server on this machine and no Docker with which to start one.
How M0 and M1 were nevertheless verified against a real PostgreSQL is described in §11.

## 6. Which parts of architecture.md are already implemented

**None.** Every one of the thirteen architectural layers is at 0% implementation.

| Layer | Implemented |
| --- | --- |
| 0 Infrastructure & cross-cutting | none |
| 1 Catalog schema (Phase 1) | none |
| 2 Commerce schema (Phase 2) | none |
| 3 Repositories | none |
| 4 Domain services | none |
| 5 Ranking engine | none |
| 6 Policy Engine | none |
| 7 LLM layer | none |
| 8 Agent Runtime | none |
| 9 Tools | none |
| 10 API (FastAPI) | none |
| 11 Payments (Razorpay) | none |
| 12 Frontend | none |
| 13 Quality & evaluation | none |

What *does* exist is a complete and accurate **analysis** of the specification in `docs/analysis/`:
a 13-layer component inventory, a dependency map with a 16-milestone build order, 45 open questions
with proposed defaults, a 100-task breakdown, and a reconciled repository structure. This
implementation adopts that repository structure and that milestone ordering.

## 7. Which parts are missing

Everything. Framed against the analysis's milestone plan, the work outstanding at the start of this
session was M0 through M15 inclusive. The specification itself is not uniformly implementable:

- **Fully specified, implementable as written:** the seven Phase-1 catalog tables (columns, types,
  PKs, FKs, unique constraints, indexes); webhook signature verification against the raw body;
  event-ID deduplication; the policy reason-code list; tool risk tiers; the twelve audit event names.
- **Specified but requiring a decision first:** the ranking weights and every feature-score formula;
  the `/api/chat` response shape; approval semantics and TTL; idempotency key scope and lifetime;
  the spending-limit scope; the agent state machine; retry and timeout values; the tool-call loop
  limit.
- **Required by the architecture but never defined anywhere in it:** the entire Phase-2 commerce
  schema at column level; the repository layer; device-identifier canonicalization; the money
  representation at the Razorpay boundary; a session/approval persistence strategy; a test
  double strategy for the LLM; local development orchestration; CI.

## 8. Conflicts between architecture.md and artifact-export.md

**There are none, and this needs stating precisely.** `artifact-export.md` is not a competing
specification. It is a Markdown export of the same analysis that produced `docs/analysis/`, and its
content matches those files section for section (same six findings, same 13-layer inventory, same 16
milestones, same 45 open questions, same 100 tasks, same file tree). It is *derived* from
`architecture.md` and carries no independent authority.

What both documents describe, and what genuinely matters, are the conflicts **internal to
`architecture.md`**. These are the ones an implementation has to resolve:

| # | Conflict inside `architecture.md` | Where | Resolution (see ADR) |
| --- | --- | --- | --- |
| 1 | Two different ranking weight sets for the same calculation: Compatibility 40 / Preference 30 / Price 20 / Relevance 10, versus Preference 0.50 / Price 0.30 / Relevance 0.20 with compatibility as a hard filter. The document states the hard-filter approach is preferred. | R§4 vs R§19 | ADR-004, ADR-005 |
| 2 | `request_approval` is listed as an LLM-callable tool, while approval is defined throughout as an explicit human act that the application records. | L§10, A§8, A§14 vs P§9, A§26 | ADR-007, ADR-009 |
| 3 | `create_order` appears in the tool list given to Claude, while the same document says it "must NOT be freely available to the LLM." | L§10, A§17 vs A§15, A§22 | ADR-009, ADR-011 |
| 4 | Two incompatible `POST /api/chat` response shapes: `{session_id, message, state, trace}` versus `{session_id, message, recommendations[]}`. | A§48 vs F§8–9 | ADR-010 |
| 5 | Build-order disagreement: the database part forbids commerce tables in the first milestone; the frontend part sequences cart work before the frontend without saying when those tables arrive. | D§36, D§39 vs F§37 | ADR-006 |
| 6 | Tool naming: `search_products(...)` in the frontend part, `search_catalog(...)` everywhere else. | F§6 vs all other parts | ADR-009 (`search_catalog` is canonical) |
| 7 | Stock disclosure granularity: tools return `available_quantity: 17`; the frontend example returns `stock_status: "IN_STOCK"`. | A§12 vs F§5 | ADR-010 |
| 8 | Two overlapping state machines — agent conversation states and order lifecycle states — share names (`APPROVED`, `POLICY_VALIDATED`, `PAYMENT_CONFIRMED`) and both are marked "finalize during implementation." | A§25 vs P§30 | ADR-007, ADR-011 |

There is also one **conflict between `architecture.md` and this project's own instructions**, which
must be recorded rather than silently absorbed:

| # | Conflict | Resolution |
| --- | --- | --- |
| 9 | `architecture.md` never defines a RelevanceScore formula; `docs/analysis/03-open-questions.md` A2 *proposes* category 0.40 / tag 0.25 / name+description 0.20 / attributes 0.15. The implementation instructions mandate category 0.40 / attribute 0.30 / text 0.20 / tag 0.10. | The mandated formula is used. The specification does not contradict it, because the specification has no formula at all; the analysis proposal was a recommendation, not a decision. Recorded in **ADR-004**. |
| 10 | `docs/analysis/03-open-questions.md` A4 proposes `PreferenceScore = 1.0` when the buyer states no preferences; the implementation instructions mandate `0.0`. | The mandated value is used. Recorded in **ADR-004**, including the ranking consequence — with zero preferences the preference term contributes nothing and ordering is decided by price and relevance alone. |

## 9. Decisions that remained unresolved before this session

The eight the analysis identified as blocking, plus two that inspection added. Each is now closed by
an ADR (Phase 1) or explicitly deferred with a named owner.

| ID | Question | Status |
| --- | --- | --- |
| A2 | RelevanceScore formula | **Closed** — ADR-004 |
| A1 / A3 / A4 | Ranking weight set; PriceScore with no budget; PreferenceScore with no preferences | **Closed** — ADR-004 |
| B1 | Device-identifier canonicalization | **Closed** — ADR-003 |
| C1 | Phase-2 commerce schema columns | **Closed on paper** — ADR-006. Not implemented; M6. |
| C3 | Session and approval persistence | **Closed** — ADR-006, ADR-007 (PostgreSQL) |
| C4 | Money representation at the Razorpay boundary | **Closed** — ADR-008 |
| D5 / D6 | May the model approve, or create orders | **Closed** — ADR-007, ADR-009, ADR-011 (no, and no) |
| E3 | Canonical `/api/chat` contract | **Closed** — ADR-010 |
| F12 | The CircuitCraft seed catalog is referenced but never supplied | **Closed by authoring** — see §12 and ADR-002 |
| **U1** | Is `L:\RazorPay\backend` intended to be this project's starting point? | **Open.** Requires the project owner. Assumed *no* — it is SQLite-backed, contradicting D§2/D§38, and lies outside the working directory. |
| **U2** | The external project brief defining the MUST-WORK / SHOULD-WORK tiers and the "pre-submission gate" (F11) | **Open external-input gap; blocks nothing.** Searched for on 2026-08-31 and genuinely absent. The six brief-derived requirements the supplied documents do state are preserved verbatim in `docs/notes/external-brief-gap.md`. |
| **U3** | How PostgreSQL is to be provisioned on this machine (no Docker, no server installed) | **Resolved in practice.** See §11. |

## 10. Adopted plan

The milestone sequence from `docs/analysis/02-dependency-map.md` is adopted unchanged, and the
repository layout from `docs/analysis/05-proposed-repo-structure.md` is adopted as the single
application root. No duplicate application root is created.

The first session delivered **Phase 0 (this document), Phase 1 (ADR-001 … ADR-014), M0
(foundation) and M1 (catalog database)**. Subsequent sessions have added **M2 (catalog read
services)** and **M3 (ranking engine)**. M4 onward is not started.

> **This document is a dated Phase-0 assessment and is not rewritten as work lands.** It records
> what the repository looked like before any code existed, and how each milestone was verified.
> §13 below is the running record of milestones completed since. The live status table is in
> `README.md`; every departure from the specification is indexed in `docs/notes/deviations.md`.

## 11. How M0 and M1 were verified

Both milestones have exit criteria phrased as *"migrations run"* and *"tests pass"*, and this
machine has neither Docker nor an installed PostgreSQL. Rather than report those criteria as
unproven, a **throwaway PostgreSQL 16.4** was provisioned from the official Windows binary archive
into the session scratchpad — `initdb` plus `pg_ctl` in user space, no installer, no Windows
service, nothing written outside the temporary directory. The full suite then ran against it.

**Result: 153 tests pass, 0 fail, 0 skip.** Two defects surfaced only under a live database and were
fixed:

1. `Category.products` was ambiguous, because the composite merchant-scoping foreign key gives
   `categories` and `products` two foreign-key paths. SQLAlchemy configures mappers lazily, so
   nothing had triggered it. Fixed by naming the foreign key, and a new offline test now calls
   `configure_mappers()` so this class of error is caught without a database.
2. A raw-SQL constraint test expected the violation at flush time; PostgreSQL raises it at execute
   time. The constraint itself was working; the assertion was in the wrong place.

**Verified without a database** (127 of the 153):

- Alembic renders the complete schema from zero in offline mode, and the rendered DDL is diffed
  clause by clause against the compiled SQLAlchemy metadata — constraint names included — so the
  models and the migrations cannot drift apart.
- Every constraint, index, foreign key and check is asserted against the metadata and against the
  compiled PostgreSQL DDL.
- The seed catalog is validated as data: SKU uniqueness, slug and token form, referential closure,
  monetary values parsed as `Decimal` and never as `float`, aliases already normalized, and every
  compatibility constraint predicate satisfied by its own product.
- The FastAPI application imports, boots through its lifespan, and serves its health endpoint.

**Verified against the live PostgreSQL 16.4** (the remaining 26):

- `alembic upgrade head` applies from zero and `alembic downgrade base` rolls back cleanly.
- The seed loads all 136 rows, and loading it a second time changes nothing.
- Fourteen constraint violations are each rejected by the constraint named in the assertion.
- The worked-example candidate query returns the right SKUs and excludes the out-of-stock,
  wrong-device and over-budget ones, with prices as `Decimal`.

The documented workflow was also run end to end: `alembic upgrade head`,
`python -m app.seed.circuitcraft`, a second seed run, `--summary`, then `uvicorn app.main:app` with
`GET /api/health` returning `200 {"status":"ok", ...}`.

Those 26 tests are marked `requires_db` and **skip with an explicit reason** when no PostgreSQL is
reachable. They are never reported as passes. `docker-compose.yml` and the runbook in `README.md`
give the one command that makes them run on any machine with Docker.


## 12. Note on seed data authorship

`architecture.md` refers to a "30–36 SKU CircuitCraft prototype" but supplies only one complete
record (AeroCase Pro / `CASE-IP16-BLK` / ₹999 / quantity 20 / compatible with `iphone_16` /
cross-sells a screen protector) plus a handful of prices and names in worked examples. The catalog
therefore has to be authored, which the analysis also concluded (F12).

It is authored under a rule: **every product is a fictional CircuitCraft own-brand item described
only by structural attributes** — material, colour, wattage, port type, cable length, capacity,
battery hours, ANC yes/no. No certifications, ratings, review counts, test results, warranty terms
or real third-party brand names appear anywhere in the seed. Every value the specification does give
is reproduced exactly. This satisfies "do not fabricate arbitrary product claims" while still
producing a catalog the ranking engine and the compatibility service can be tested against.

## 13. Milestones completed after this assessment

### M2 — catalog read services

`app/repositories/` (product, variant, inventory, compatibility) and `app/services/`
(`CatalogService`, `CompatibilityService`, `InventoryService`), returning frozen `app/domain/` types
rather than ORM rows. Compatibility resolution implements ADR-003 end to end: a device phrase is
normalized, resolved against `compatibility_targets`, and either yields a canonical identifier or a
first-class `UnresolvedTarget` the caller must handle. Nothing guesses.

### M3 — ranking engine

The whole of `architecture.md` Part R, in `app/ranking/` — `weights.py`, `filters.py`, `scorers.py`,
`ranker.py`, `explain.py`, `combinations.py` — plus `RecommendationService`, which is the only part
of M3 that opens a query.

**Exit condition (ADR-004): met exactly.** The R§10 worked example reproduces under the
`explainability_demo` profile — AeroCase Pro `0.796800`, ShieldCase Premium `0.786800`, against the
specification's stated `0.7968` and `0.7868` — and R§8's own price examples (`0.67`/`0.33`, and
`0.334`/`0.134`) come out of the scorer rather than the fixture.

Task coverage against `docs/analysis/04-task-breakdown.md`:

| Task | Delivered in |
| --- | --- |
| RANK-01 weight profiles as configuration | `app/ranking/weights.py`, `RANKING_PROFILE` / `RANKING_TOP_K` settings |
| RANK-02 hard-constraint filter | `app/ranking/filters.py` — one function per constraint |
| RANK-03 PreferenceScore | `app/ranking/scorers.py` |
| RANK-04 PriceScore | `app/ranking/scorers.py`, incl. every degenerate branch |
| RANK-05 RelevanceScore | `app/ranking/scorers.py` — the formula ADR-004 supplies, since R§9 gives none |
| RANK-06 aggregator + Top-K | `app/ranking/ranker.py` |
| RANK-07 structured explanation | `app/ranking/explain.py`, `Explanation`, `RecommendationLabel` |
| RANK-08 multi-product budget combination | `app/ranking/combinations.py` |
| RANK-09 cross-sell candidates | `RecommendationService.cross_sell_candidates` |
| RANK-10 no-match behaviour | `RecommendationOutcome`, `relaxed_constraints`, `alternatives` |
| RANK-11 ranking tests | `tests/ranking/` (164 tests) + `tests/services/test_recommendation_service.py` (20) |

**How M3 was verified.** A throwaway PostgreSQL 16.4 was provisioned exactly as described in §11 —
unpacked from the official Windows binary archive into the session scratchpad, `initdb` plus
`pg_ctl` in user space, listening on a non-default port, nothing written outside the temporary
directory.

**Result: 520 tests pass, 0 fail, 0 skip.** 375 of them need no database at all, because
`app/ranking/` is pure by design; the remaining 145 ran against the live server, including 20 new
`RecommendationService` integration tests that exercise the seed catalog's deliberately-planted
cases — the cheaper iPhone 15 case that must never appear, the zero-quantity clear case, the
₹1,799 leather folio offered as a labelled over-budget alternative, and `pixel_9` as a resolvable
device with no compatible products.

One change to existing code was needed and is recorded as A17 in `docs/notes/deviations.md`: the
attribute-comparison predicates moved out of `CompatibilityService` into `app/attributes.py` so the
ranker's required-specification constraint could share them. `constraints_satisfied` remains as a
thin wrapper, and all eighteen of the M2 suite's predicate assertions are now also asserted in
`tests/test_attributes.py`, which runs without a database.

### M4 — LLM layer

`app/llm/` — the probabilistic side of the boundary, and the first code in this repository that
talks to a model. Six modules and two prompts:

| Module | What it is |
| --- | --- |
| `models.py` | Provider-agnostic transport types — `Message`, `ModelResponse`, `ToolCall`, `TokenUsage`, `StopReason` |
| `errors.py` | The six failure modes L§46 names, as types, with `is_transient` deciding retries |
| `client.py` | The Anthropic client. The **only** module in the repository that imports the SDK |
| `schemas.py` | The structured buyer intent (L§5), as Pydantic, with `loads_decimal` |
| `extractor.py` | `IntentExtractor` — natural language in, validated intent out (LLM-03, LLM-07) |
| `tool_schemas.py` | The eight tools' names, descriptions, argument models and validation (LLM-05) |
| `prompts/system_prompt.md` | The twelve behavioural rules (LLM-04), version-controlled |
| `prompts/intent_extraction.md` | The extraction contract, version-controlled separately |

**Exit condition: met.** `docs/analysis/02-dependency-map.md` states M4's as *"natural language →
validated structured intent, offline-testable"*. All 198 LLM tests run with no API key, no network
and no database, in under a second.

Task coverage against `docs/analysis/04-task-breakdown.md`:

| Task | Delivered in |
| --- | --- |
| LLM-01 Claude client — env key, timeout, bounded retry, error handling | `app/llm/client.py` |
| LLM-02 structured intent schema | `app/llm/schemas.py` |
| LLM-03 intent extraction, clarification detection, no catalog facts | `app/llm/extractor.py` |
| LLM-04 system prompt, version-controlled | `app/llm/prompts/system_prompt.md` |
| LLM-05 tool schema definitions | `app/llm/tool_schemas.py` |
| LLM-06 tool-call handling — **parse and validate only** | `validate_tool_arguments`; execution is M5's `AGENT-02` |
| LLM-07 conversation context — preserve and update intent, avoid unnecessary context | `merge_intent`, `IntentExtractor.max_history` |
| LLM-08…LLM-12 | Not M4. They need the runtime (M5), the cart (M7) and the Policy Engine (M9). |

Three decisions were made here and are recorded in `docs/notes/deviations.md`:

1. **Extraction asks for text JSON, not a tool call** (R29). Tool arguments arrive from the SDK
   already JSON-decoded, so `1500.10` would be a `float` before this application saw it, and a
   `Decimal` built from a lossy binary float is still lossy. Text output can be parsed with
   `parse_float=Decimal`. This is the only interception point that exists, and `Budget` rejects a
   `float` outright so that any future shortcut around it becomes a test failure.
2. **Carry-forward is by omission; removal is by `null`** (R27). L§26 requires the intent to be
   updated across turns and never says what updating means. A field the model leaves out inherits;
   a field it sets to `null` is cleared. Both are needed — L§26's own "Around 1500" example must
   inherit the device, and a buyer withdrawing a budget must be able to.
3. **One bounded repair attempt** (A26). The extractor tells the model what failed validation and
   asks once more. It never edits the output, never coerces a wrong type, and never accepts a
   differently-shaped payload.

**Open question F1 is closed by ADR-015**, which was owed before this milestone. The seam is the
one-method `LLMClient` protocol; the model is faked at that protocol and the SDK only inside
`tests/llm/test_client.py`; no test calls a live model at any milestone. E2 is closed by the same
ADR, confirming the analysis document's proposed retry and timeout values against the built client.

**How M4 was verified.** The throwaway PostgreSQL 16.4 of §11 was restarted and the whole suite run
against it. **Result: 721 tests pass, 0 fail, 0 skip.** 576 of them need no database; the 145
`requires_db` tests are unchanged from M3, because M4 adds no code that opens a query — by
construction, since `tests/llm/test_boundaries.py` forbids `app/llm` from importing a service, a
repository or SQLAlchemy at all.

The 198 new tests break down as: 43 on the tool registry (that `create_order` is absent, that no
tool accepts a price or a stock level, that `request_approval` has no field capable of expressing
approval), 32 on the extractor, 30 on the client (bounded retries, mapped provider errors, and the
L§45 refusal to send a prompt containing a configured secret), 29 on the schema, 29 on the prompts,
19 boundary guards, and 16 on the transport types and the error taxonomy.

One existing test changed. `tests/services/test_service_boundaries.py` asserted that `app/llm` did
not exist — true through M3, and the wrong rule from M4 onward. It now asserts the rule that
replaces it: `app/agent` still must not exist, and nothing on the trusted side imports `app.llm`.

**What M4 does not prove.** No test here shows that Claude obeys the prompts, because that is not
knowable offline; ADR-015 states this cost explicitly. Offline tests prove the application handles
model output correctly. They cannot prove the model produces good output — which is exactly why no
correctness property of this system depends on it doing so.
