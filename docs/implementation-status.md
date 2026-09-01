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
against it. **Result: 719 tests pass, 0 fail, 0 skip.** 574 of them need no database; the 145
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

### M5 — agent runtime (read-only)

The layer where a model's request becomes a validated action. `app/agent/` is the only package that
imports both `app.llm` and a service, and a standing guard now asserts that: the per-file rules say
what may not import what, and `test_the_runtime_is_the_only_place_the_two_sides_meet` says where the
exception lives, so a second door onto the boundary cannot appear unreviewed.

**What landed.** `errors.py` (the F§25 vocabulary and the internal one, with the single mapping
between them), `state.py` and `app/domain/conversation.py` (A§25's machine, finalized), `context.py`
(`AgentContext` and A§50's `TurnMemory`), `registry.py`, five tool handlers under `tools/`,
`executor.py` (the A§19 pipeline, written once), `runtime.py` (A§49's loop with A§51's six
terminations), `app/services/session_service.py`, migration `0003`, and `POST /api/chat` with the
ADR-010 request and response models.

**The exit condition is a test, not a claim.** `tests/agent/test_exit_condition.py` runs *"Find me a
case for iPhone 16 under ₹1500"* against a real PostgreSQL, the real seeded catalog, the real
compatibility resolver and the real ranking engine, and asserts a grounded Top-3: every row has a
SKU, a price at or under the ceiling, a purchasable stock status, a category, and a `reason` from
the engine's own label set. Companion tests assert the iPhone 15 case never survives an iPhone 16
requirement, that an unknown device asks the buyer while `pixel_9` — resolvable, with nothing
compatible — is a legitimate no-match, and that a product the model invents in prose is absent from
the structured half.

**Three properties hold whatever the model does**, and each is asserted by scripting a model that
misbehaves:

1. *Recommendations come from the ranker.* The response is assembled from `TurnMemory`, which the
   tools wrote from `RecommendationService`. A model told to recommend `NOVA-X9` produces a turn
   whose `recommendations[]` does not contain it.
2. *No tool call can move money.* Only LOW-tier read tools are registered; `create_order` is absent
   from the registry, from `HANDLERS`, from `app/agent/tools/`, and is refused by `build_registry`
   even when explicitly requested. A call to it reports **forbidden**, not unknown, so an injection
   attempt is legible in a log rather than looking like a typo.
3. *A failure is reported, never filled in.* A tool that raises `RuntimeError("relation ... does not
   exist")` reaches the model as `INTERNAL_ERROR` and a sentence; the exception text is asserted
   absent.

**Sessions came forward from M6** (deviation A28). Open question C3 is closed by ADR-006 as
PostgreSQL and the task breakdown gives AGENT-01 the job of closing it, which a dictionary cannot
do. Migration `0003` adds `sessions` and `session_messages` only; the nine tables that hold money,
carts, orders and approvals remain M6, and the guard that keeps them out was narrowed to those nine
and paired with a positive assertion about the two that moved.

**How M5 was verified.** A throwaway PostgreSQL 16.4 was provisioned as in §11 — `initdb` plus
`pg_ctl` in user space, nothing written outside the session scratchpad — and the whole suite run
against it. **Result: 920 tests pass, 0 fail, 0 skip.** 731 of them need no database. The documented
runbook was then run end to end: `alembic downgrade base`, `alembic upgrade head` (through `0003`),
`python -m app.seed.circuitcraft`, and the application booting through its lifespan with
`GET /api/health` returning `200 {"status":"ok"}` against the live database.

One category-slug error surfaced only under a live catalog and was fixed in the tests: the seed's
slugs are `phone_case` and `charger`, not `phone-cases` and `chargers`. The tool was right to refuse
the unknown category — that is `CATEGORY_NOT_FOUND` doing its job — and the assertion was wrong.

One fixture defect surfaced the same way. Promoting the seeded-database fixtures to
`tests/conftest.py` so the agent and service tests share one definition changed `seeded_engine`'s
package scope into an effectively session-wide one, and
`tests/db/test_catalog_integrity.py` deliberately downgrades to base at its own teardown. Every
module running after it then queried a database with no tables. Fixed by scoping the fixture to the
module, which re-ensures the schema; the reason is now in the fixture's docstring, because the
scope is load-bearing and looks arbitrary otherwise.

**What M5 does not prove.** `[ ] Runtime can call Claude Sonnet` (A§56, L§50) is **still not
verified**, for the reason ADR-016 records: this machine has no Anthropic key. The runtime depends
on the `LLMClient` protocol and is exercised end to end against a fake, so everything the
application does with a model's output is covered; that a live Claude drives the loop is not. It
stays open until a key is available and the check is run by hand.

### M6 — commerce schema

The money path's storage, created before anything can write to it. Migration `0004` adds ADR-006's
remaining nine tables — `carts`, `cart_items`, `approvals`, `idempotency_keys`, `orders`,
`order_items`, `payments`, `webhook_events`, `audit_events` — with the ORM models under
`app/db/models/` and the enums defined once in `app/domain/commerce.py`.

**M6 adds no behaviour, and a guard now says so.** The old boundary test forbade any module under
`app/` whose name mentioned a cart, an order, a payment or a policy, which was right while none of
them had a table. It narrows to what it was actually protecting: `app/policy/`, `app/payments/`,
`cart_service.py`, `order_service.py`, `audit_service.py` and the cart, order and webhook routes
must still not exist. A table is inert; a service that writes to one is not. A companion test
asserts no M2 or M3 read service imports a commerce model.

**Every exit test ADR-006 names is a test that the database refuses**, which is the point of the
milestone. The load-bearing one is `orders.approval_id NOT NULL`: an order row without an approval
cannot be inserted, and no code path — reviewed or otherwise — can put one there. The partial unique
indexes reject a second active cart per session and a second approval of one cart version, while
still permitting the ORDERED/ABANDONED and SUPERSEDED/EXPIRED history that ADR-014's price-drift
recovery reads. `UNIQUE(provider, event_id)` rejects a duplicate webhook. Four foreign keys reject
orphans, and `ON DELETE RESTRICT` stops a variant that appears in a placed order from being deleted
— the financial record outlives the catalog row.

**The enums are defined once.** ADR-006 requires it, and `tests/db/test_migrations.py` enforces it
by diffing the rendered DDL against the compiled metadata; `app/db/models/_enums.py` renders every
`CHECK` from a tuple in `app/domain/commerce.py`, so a new value that never reached a migration
fails offline. One live test reads `pg_get_constraintdef` back and asserts the constraint is not
*narrower* than the enum either, which the metadata diff cannot see.

**How M6 was verified.** The same throwaway PostgreSQL 16.4 of §11. **Result: 951 tests pass, 0
fail, 0 skip**, 735 of them needing no database. `alembic downgrade base` then `alembic upgrade
head` runs all four migrations in each direction cleanly, and the seed loads afterwards.

Three defects surfaced, all in the test scaffolding rather than the schema, and all only under a
live database:

1. The seeded-database fixture asked *"does the catalog exist?"* and migrated only if not. A
   database left at an older revision therefore stayed there, so every test written against a `0004`
   table failed with "relation does not exist". It now runs `alembic upgrade head` unconditionally,
   which is idempotent and a no-op at head.
2. `tests/db/test_migrations.py`'s DDL parser matched `CREATE TABLE` and `CREATE INDEX` but not
   `CREATE UNIQUE INDEX`, which is not a prefix of either. Every unique index in the schema — the
   two partial ones ADR-006 relies on included — was being compared against nothing. Widening the
   parser is a real strengthening of the anti-drift test, not a fix for M6.
3. `variant_id` and `product_id` lived in the services conftest and the commerce tests needed them;
   promoted alongside the seeded-database fixtures.

ADR-006's implementation note calls its migration `0003_commerce_schema`. That number went to the
session tables in M5, so this is `0004` (deviation A32). Revision numbers follow the order things
were built; renumbering to match a document would mean rewriting applied history.

### M7 — cart

The Cart Service, the `propose_cart` tool, and the four cart endpoints F§26 names. Its exit
condition is two claims and both are tests: *the cart total is backend-computed*, and *the version
increments on mutation*.

**Backend-computed is enforced by absence.** No service method, no tool argument and no request
model has a price, subtotal or total field. `test_no_method_accepts_an_amount` walks the service's
signatures and asserts none of them contains a money word, because a method that quietly ignored a
price would still be a method someone believed they had used; the API models are `extra="forbid"`,
so a client sending `unit_price` gets a 422 rather than a silently-dropped field.

**The version is what an approval will bind to** (A§27, F§13), so every case where it moves and
every case where it does not is a case where a stale approval is or is not detected. Adding,
changing a quantity and removing all increment it. Marking a cart ORDERED does not — the composition
did not change, and the approval must stay matched to the order it authorized. The subtle one is
`refresh`: nothing the buyer did changed, but what they would be charged did, so the version moves
and the old approval goes stale. That is the primary failure scenario the specification names
(A§28), and M7 handles it as an ordinary cart change rather than as an incident.

**A view reports drift without applying it.** `unit_price_snapshot` is display and drift-detection
state, never authority (RULE 6, RULE 12): reading a cart re-reads every live price and reports any
difference as `price_changes`, in both directions, while leaving the stored total alone. Correcting
it on read would change what the buyer is charged without their seeing it happen; `refresh` is the
deliberate act that does.

**`propose_cart` is the first MEDIUM-tier tool, and the executor gained the authorization A§22 asks
for.** MEDIUM writes application state, so it needs an owner for that state: the session the
*runtime* established, carried on `TurnMemory`. No tool schema has a `session_id` field, so a model
has no argument through which to name somebody else's cart, and a MEDIUM call in a turn with no
session is refused rather than defaulted. There is still no HIGH tier and there never will be —
`create_order` would have been the only one and it is not a tool at all.

The tool computes nothing, authorizes nothing, and replaces rather than appends: a second proposal
is a correction of the first, because "actually, just the case" must not produce a cart holding it
twice. Every variant is resolved and every stock level checked before anything is written, so a
proposal naming one bad variant leaves the existing cart intact rather than half-replaced.

**How M7 was verified.** The throwaway PostgreSQL 16.4 of §11. **Result: 1018 tests pass, 0 fail, 0
skip**, 761 of them needing no database. The cart service and API tests run against the real seeded
catalog, so "backend-computed" means computed from what the database actually says.

Two things surfaced and were fixed rather than accommodated. The seeded catalog's charger SKUs are
`CHARGER-20W` and `CHARGER-30W`, not the `CHG-` prefix a test assumed. And a parametrized bounds
test carried a `pytest.skip` for its zero case; this project treats a run with skips as an
incomplete run, so the case was made meaningful instead — `add_item(0)` is not an operation and must
be refused, which is a different rule from `set_quantity(0)` meaning "remove this line".

`POST /api/cart/approve` is deliberately absent. Approval is M8: it is the only path that may write
an `APPROVED` row, and it mints the idempotency key (ADR-007, ADR-013).

### M8 — approval

The record that says a human authorized a payment, and the machinery that decides when it stops
being true. Its exit condition is one sentence — *a stale approval is rejected by test* — and
ADR-007 names six tests; all six exist.

**Only a buyer action writes `APPROVED`, and that is a property of the type system.**
`ApprovalService.request` - what the agent's `request_approval` calls - has parameters
`(self, session_id, cart)` and no `status`. There is no argument, no overload and no refactor of the
tool that produces an authorization, which `test_request_has_no_parameter_that_could_write_approved`
asserts by walking the signature rather than by trying and failing to persuade it. A test that
called the tool and checked the result came back `PENDING` would pass against an implementation that
wrote `APPROVED` under some other condition; this one does not.

`POST /api/cart/approve` is the only path that can answer. P§9 is the sentence the split enforces:
"Show me the cart" is not approval, and neither is "How much is it?".

**An approval binds to five things** and each test breaks exactly one of them, because a check that
only fires when everything changes at once is a check that never fires. The fingerprint is the
interesting one: a total is not a composition, and ₹1,499 + ₹299 reaches the same ₹1,798 as ₹1,299 +
₹499 while being a completely different order. `items_fingerprint` is defined once in
`app/domain/approval.py` because ADR-007 requires the writer and the Policy Engine to share it - two
implementations would eventually disagree, and the disagreement would present as an approval that
silently stopped matching its own cart.

**Invalidation happens inside `CartService._recompute`**, the one place a cart version is ever
assigned. Putting it there rather than at each call site is what makes it unconditional: a mutation
added in some later milestone cannot forget, because the only way to change a cart is through the
function that also invalidates its authorization. A price *decrease* supersedes too (ADR-007 rule 2,
closing D2) - the buyer approved a specific total, and charging a different one, cheaper or not, is
charging an amount nobody authorized.

**Expiry is evaluated at the moment of use.** `ApprovalView.authorizes` refuses an elapsed row
whether or not `expire_stale` ever ran, so a sweeper is an optimization and never the mechanism.
`expires_at` is stored rather than computed at read time, so changing `APPROVAL_TTL_SECONDS` never
retroactively revives or kills an approval that already exists.

**The approve route re-prices before it checks the version**, deliberately. A catalog change since
the buyer's screen was drawn bumps the version, so the version they submitted no longer matches and
they are asked to look again rather than authorizing a total that is no longer real. That is A§28's
scenario entering through the front door, and `test_a_price_change_before_approval_is_caught_at_the_edge`
is it end to end.

**How M8 was verified.** The throwaway PostgreSQL 16.4 of §11. **Result: 1071 tests pass, 0 fail, 0
skip**, 781 of them needing no database.

**One gap, recorded rather than closed.** ADR-007 calls for an `APPROVAL_SUPERSEDED` audit event on
every supersession. `audit_events` exists from M6; the Audit Service is M13. `supersede_for_cart` is
written to be the single place that emission hooks into, and no audit row is written yet.

### M9 — Policy Engine

The last thing that runs before money can move, and the one component whose verdict nothing else
may override. P§7 states the property: *"The result must be generated by application code. Claude
should not be able to override it."*

**The engine is pure**, and that is the design rather than a convenience. Input
`TransactionContext`, output `PolicyDecision`; no session, no query, no clock, no network, no model.
It cannot be talked into anything because it has no access to anything that could be talked to, and
all forty-four of its tests run without a database because constructing an adversarial state costs
one dataclass. Reading live prices and taking `SELECT ... FOR UPDATE` on the inventory rows is
deliberately *not* its job - that is M10's, inside the order transaction - so the freshness rule
lives in one reviewable place and the decision logic in another that is exhaustively testable.

**All ten P§6 rules are evaluated; evaluation never stops at the first failure.** `reason_codes` is
a list because a buyer who fixes the first problem only to meet the second has been served badly by
a system that knew about both. Codes are deduplicated with order preserved: a deactivated product
fails rules 3 and 4 for one underlying cause, and the buyer hears it once.

**M9's exit condition is that price drift and out of stock both FAIL with the right code**, and both
do. A price *decrease* fails too (ADR-007 rule 2, closing D2) - the buyer approved a specific amount,
and charging a different one, cheaper or not, is charging an amount nobody authorized. The decision
carries `validated_total` even on a FAIL, because P§7's own example does: the number that caused the
refusal is exactly the number the buyer must now be shown.

Every rule is broken **alone**, with everything else valid, because a rule that only fires when
several things are wrong at once is a rule that never fires by itself. One test then breaks five at
once and asserts all five codes come back.

**The engine never reads conversation state**, and `test_conversation_state_cannot_reach_the_engine`
asserts that structurally: there is no field on `TransactionContext` through which it could arrive. A
session says `APPROVED` only because the agent set it; only an `approvals` row is evidence (ADR-007,
closing C7).

`app/policy/` joins the deterministic packages in `test_service_boundaries.py`. Of everything on that
list it is the one that must least be reachable from the probabilistic side.

**How M9 was verified.** **Result: 1115 tests pass, 0 fail, 0 skip**, 825 of them needing no
database - the 44 new ones included, since the engine has no database to need.

One wart was fixed rather than left: the ten rule functions originally took an evaluation instant
only one of them used, which a type checker correctly flagged nine times. The instant is now
resolved onto the context once before dispatch, which removes the unused parameter and makes the
context self-describing - a decision is about a moment, and the moment is part of the input it was
made from.

### M10 — orders and idempotency

The money path, up to the point where a provider would be called. `OrderService` implements ADR-011
steps 1 through 8 in one method: load live, lock the inventory rows, evaluate policy, and either
refuse with reason codes or insert the order and its immutable lines. Steps 9 and 10 - the Razorpay
call and the audit write - are M11 and M13.

**An order in `ORDER_CREATED` with a null `razorpay_order_id` is the designed state, not a broken
one.** ADR-011 commits the internal order *before* the provider is called, because the reverse
ordering would allow a provider order with no local record, which is unreconcilable. M10 therefore
ends exactly where the ADR says the commit belongs.

**M10's exit condition - a duplicate request produces exactly one logical order - is asserted three
ways.** The service returns the stored answer with `replayed=True`; the database holds one row; and
a raw insert reusing the same `idempotency_key_id` is refused by the `UNIQUE` constraint even with
every application check bypassed. Application logic makes the common case pleasant; the constraint
makes the rare case correct.

**The backend mints the key, at approval time** (ADR-013). `POST /api/cart/approve` creates it in
the same transaction as the approval and returns it; the client presents it on `POST /api/orders`. A
cart mutation bumps the version and supersedes the approval, so the next approval mints a new key -
P§16's "fresh idempotency key" obtained as a consequence of the approval rules rather than as a
separate mechanism anyone has to remember.

`FOR UPDATE NOWAIT` claims the key rather than a conditional status update (deviation A42): ADR-006
fixes the status column at three values and a key minted at approval time is already `RESERVED`, so
there is no fourth state to move through. The lock is the mutex ADR-013 asks for and is strictly
stronger - it also serializes the read of `response_snapshot` a replay depends on. A second request
that cannot take it gets `409 ORDER_IN_PROGRESS`: a race lost cleanly rather than resolved by
whoever arrives second.

**Nothing from the client is authoritative.** `CreateOrderRequest` carries a session, a cart, a
claimed `cart_version` and the key. It has no amount, no price, no item list and no currency, so
F§17's forged `amount = ₹1` is not defeated by validation - it has nowhere to be submitted, and
`extra="forbid"` makes the attempt a 422 rather than a field quietly discarded.

**ADR-008's minor-unit conversion arrives here** rather than in M11, because
`orders.total_amount_minor` is written when the order is created. `app/payments/money.py` holds the
two functions and nothing else - no client, no credentials, no network call - so the boundary guard
narrows from "`app/payments` must not exist" to naming the Razorpay client itself. A new guard
asserts no module outside that package multiplies or divides by 100.

**How M10 was verified.** **Result: 1181 tests pass, 0 fail, 0 skip**, 852 of them needing no
database.

One real defect surfaced, and it was in the test scaffolding rather than the code. The API tests
inject the test's own session, and a route that finishes its work calls `db.commit()` - correctly,
it is the unit of work - which ended the test's transaction and made its setup permanent. One test
setting a stock level to zero then broke a *different* test's fixture several tests later, in a way
that read as a bug in the code under test. The session fixture now uses
`join_transaction_mode="create_savepoint"`, so a route's commit releases a savepoint and behaves
exactly as it does in production while the outer transaction still rolls back.

### M11 - Razorpay orders (code complete; live call unverified)

ADR-011 step 9, the checkout handoff of P§21, and the one module in this application that talks to
a payment provider.

**The provider call happens after the commit, and that ordering is the guarantee.**
`attach_provider_order` is a separate method rather than the tail of `create_order`, so a failure
leaves the order in `ORDER_CREATED` with a null `razorpay_order_id` - visible, retryable, auditable
- rather than rolling back a purchase the buyer authorized. The route logs the failure and returns
the order; `POST /api/orders/{id}/checkout` retries it, reusing the same internal order and the same
idempotency key, so a network failure cannot produce two provider orders.

**The client takes an `Order`, not an amount.** Its signature is `(self, order)` and the figure sent
is `orders.total_amount_minor` read from the row. That is ADR-011's "nothing from the client is
authoritative" surviving the last step of the path. It also checks the amount that comes *back*: a
provider returning a different figure would mean a payment page showing something nobody approved,
and this is the last point at which that can still be compared against what was authorized.

**The seam is a two-method protocol**, exactly as ADR-015 does for the model, and `sdk.py` is the
only module that imports the Razorpay package - asserted by the same kind of AST walk that holds
`client.py` as the sole importer of the Anthropic SDK. `create` and `fetch` are the complete list of
things that can happen to a provider from here: no capture, no refund, and no way to ask whether a
payment succeeded, because that question is answered by a verified webhook and nowhere else
(ADR-012).

**Secrets never leave.** `checkout_config` returns six keys, asserted as an exact set, because a
field that ever echoed configuration wholesale would be caught by checking values rather than by
trusting a docstring.

**How M11 was verified, and what was not.** **Result: 1201 tests pass, 0 fail, 0 skip**, 872 of them
needing no database. All twenty Razorpay tests run with no credentials and no network.

**M11's stated exit condition - a policy PASS producing a real test-mode Razorpay order - has NOT
been performed.** This repository has no Razorpay test key: `RAZORPAY_KEY_SECRET` in `.env` is still
`REPLACE_ME`. Everything the application does with a provider response is covered; that a real
test-mode order comes back is not, and cannot be without credentials. The doubles under
`tests/fixtures/razorpay.py` are shaped from Razorpay's published order API and are explicitly *not*
recorded from a live call - a hand-written fixture claiming to be a recording would be the fiction
ADR-015 rejects for the model.

This is the second unperformed live check in the project, alongside M4's Claude connection
(ADR-016). Both are recorded rather than closed, and both need a credential this machine does not
have.

### M12 - webhook

Where payment truth enters. ADR-012 and P§22-P§28, and the milestone where the difference between
M11 and M12 matters: M11's exit condition genuinely needs a Razorpay credential, and M12's does not.
The signature is HMAC-SHA256 over the raw body with a secret the test controls, so the entire
verification path is exercisable offline - and it is.

**Verification runs against the raw bytes.** The route is `async`, takes `Request`, and reads
`await request.body()` before anything parses it. `json.loads` followed by `json.dumps` does not
reproduce the original bytes, so a signature checked against re-serialized JSON proves nothing
(P§24). One test posts the same JSON document with one space added and asserts a 400 - the same
document, different bytes, correctly rejected. Another asserts the route's signature binds no
Pydantic model, because adding one looks like an improvement and would silently break the guarantee.

**Deduplication is the UNIQUE(provider, event_id) constraint**, not a lookup: two simultaneous
deliveries would both pass a "have I seen this?" query. The insert is wrapped in a SAVEPOINT so the
violation does not poison the outer transaction, since a duplicate is a normal outcome rather than a
failure.

**Handlers assert a state rather than advance one** (P§27), so applying the same event twice or a
late-arriving earlier event after a later one converges. A payment failure arriving after a capture
is logged and ignored: money that arrived does not un-arrive because an earlier attempt's failure
was delivered slowly.

**Nothing is ever dropped.** An event for an unknown order is stored with a null `order_id` - it may
have arrived before the order was committed, or belong to another system sharing the account, and
the stored row is what a reconciliation reads. An unsubscribed event type is stored `IGNORED`,
because silently discarding it would make a future subscription change invisible. Both answer 200,
as does a duplicate, because Razorpay retries anything else and all three are correctly handled.

**How M12 was verified.** **Result: 1226 tests pass, 0 fail, 0 skip**, 874 of them needing no
database.

One flaw in the route surfaced through a test and was fixed rather than worked around. The
signature-rejection path called `db.rollback()`, which looked defensive and was wrong: verification
runs before the body is parsed and long before anything is written, so there is nothing of that
request's to undo, and the rollback could only discard work belonging to whatever else shared the
transaction. It showed up as a test fixture vanishing mid-test, which is exactly the shape the
production bug would have taken.

### M13 - audit and trace

The durable record of how a transaction reached its outcome, and the milestone that closes the gap
M8 recorded against ADR-007.

**A§40's distinction is the shape of this milestone.** The agent trace is per turn, returned in the
response and never persisted (ADR-010, closing E6) - it explains one conversation to a developer,
and it has existed since M5. The audit log is durable and append-only, and explains a *transaction*
to whoever asks afterwards. M13 adds the second.

**M13's exit condition - a full transaction is reconstructable from the audit events - is one test
that walks a whole purchase** (cart, approval, policy, order, provider order, verified webhook) and
then reads the story back from `audit_events` alone, touching no other table. Writing it found a
real gap: `PAYMENT_WEBHOOK_RECEIVED` was emitted before the order lookup and therefore carried no
order id, so a delivery could not be tied to the order it was about. It is now emitted after the
lookup and still written when the order is unknown, because the arrival is a fact either way (P§27).

**One named method per event type**, sixteen of them, rather than a generic `record(type, ...)`.
They look repetitive and that is the point: each names exactly what must be captured, so a call site
cannot omit the reason codes from a `POLICY_FAIL` or both totals from a `PRICE_CHANGED`. A generic
writer would put that responsibility on every caller and lose it at the first hurried one.

**Attribution is checked, not assumed.** `USER_APPROVED` is written with actor `USER` and asserted
to be - that row is the record that a human authorized a payment, and `AGENT` there would make the
log disagree with the architecture it exists to evidence. Cart creation is `AGENT`, policy is
`SYSTEM`, payments are `RAZORPAY`.

**Append-only is enforced where a developer meets it.** `AuditRepository` exposes `append` and reads
and has no update or delete; a test asserts that by walking its method names, and another asserts
the table has no `updated_at`. In deployment the application's role is granted INSERT and SELECT on
it and nothing else.

**The four events beyond RZP-07's twelve earn their place** in the failure paths, and each is
tested through the code that emits it rather than by calling the writer directly:
`APPROVAL_SUPERSEDED` on a cart mutation, `PRICE_CHANGED` with both totals, `INVENTORY_FAILURE` with
the SKU but *not* the stock level (ADR-009, closing E5), and `WEBHOOK_SIGNATURE_REJECTED` with no
order id, because an unverified request names nothing this application is entitled to believe.

**How M13 was verified.** **Result: 1246 tests pass, 0 fail, 0 skip**, 880 of them needing no
database.

The commerce-behaviour guard that has narrowed at every milestone since M6 now has an empty list,
and is deliberately kept rather than deleted. An empty guard that still runs is a guard somebody can
extend; a deleted one is a rule somebody has to remember. It is joined by two new ones asserting
what M13 must keep true: the audit writer imports no service that could change an outcome, and its
repository offers no way to rewrite history.

### The provider question, settled after M4 (ADR-016)

A `GroqClient` and a key-prefix `build_client` were added to `app/llm/` after M4 and committed as
provisional (`3b483ed`), because a Groq key was available on this machine and an Anthropic key was
not. **ADR-016 removes both.** L§44 names Claude Sonnet as the AI layer, L§48 repeats it as
DECISION 1, and L§50 and A§56 each make it a box that must be ticked — `[ ] Claude Sonnet
connected`, `[ ] Runtime can call Claude Sonnet`. "Supported Claude API interface" widens the
interface, not the model: it admits Bedrock and Vertex, which serve Claude. Groq does not serve
Claude.

The review that preceded the removal found the client was not merely untested. Its `_STOP_REASONS`
was the Anthropic table with one key renamed, so against Groq's OpenAI-compatible `finish_reason`
the value `length` would have mapped to `UNKNOWN` rather than `MAX_TOKENS` — leaving
`ModelResponse.is_truncated` permanently `False` and letting a **truncated intent pass as a
complete one**, which is the fabrication L§30 and A§41 forbid. The tool-schema converter was a
documented no-op, and `ToolCall.arguments` was built with `dict()` over what the OpenAI shape
returns as a JSON string. These are the defects a fake-SDK suite catches on its first assertion and
a live smoke test masks, which is ADR-015's argument restated as evidence.

**A gap this leaves open, recorded rather than closed.** This machine has no Anthropic key, so the
manual live verification of M4 — and L§50's `[ ] Claude Sonnet connected` — has **not been
performed**. It is not satisfied by connecting a different model. Nothing in the build depends on
it: no test may call a live model at any milestone (ADR-015), the whole suite runs with no key, and
M5 needs none either. The item stays open until a Claude key is available and the check is run by
hand.

Removing `groq_client.py` drops the two `tests/llm/test_boundaries.py` import guards it had added,
whose parametrization walks the files in `app/llm` — the count is a property of the package's
contents, not only of the tests written for it. Three new standing guards replace them and then
some, bringing the suite to **722 tests, 577 of them needing no database**: that no non-Claude model
SDK is imported anywhere under `app/`, that no `test_`-named module lives outside `tests/`, and that
`build_client` returns an `AnthropicClient` even when handed a `gsk_`-shaped key.

The first of those closes the hole this episode exposed. `test_client.py`'s single-importer guard
asserts `anthropic` is imported from exactly one file, and it stayed green for the whole life of the
Groq client — because Groq is not the Anthropic SDK. "One importer of *this* SDK" was never the same
claim as "one model SDK".

The two live-network scratch scripts at the backend root, `test_groq_api.py` and
`test_client_detection.py`, are removed with it. They were never collected (`testpaths = ["tests"]`)
but were `test_`-named and made real API calls, which is the shape ADR-015 rules out.
