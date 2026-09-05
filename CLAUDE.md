# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

---

## 🔒 LOCKED: the LLM provider is Groq

**GROQ IS THE REQUIRED AND LOCKED LLM PROVIDER.** This is permanent unless the project owner
explicitly changes it. Never migrate, or recommend migrating, to Anthropic, Claude, OpenAI, Gemini
or any other provider.

The authority is **[ADR-018](docs/decisions/ADR-018-groq-as-the-locked-llm-provider.md)**, which
supersedes ADR-016 in full. `architecture.md` names Claude Sonnet (L§44, L§48, L§50, A§56) and
**must not be followed on this point** — that file is the specification and is never edited, so the
deviation lives in the ADR instead. ADR-016 is retained only as history and its conclusion is void.

`GROQ_API_KEY` is read by `app/llm/client.py` and nowhere else, and **must never reach frontend
code** — not in a source file, not in a `VITE_`-prefixed variable, not in an API response. Never
print, log, commit or document a key value.

**Implemented and live-verified** (M4-R, 2026-09-02). The concrete client is `GroqClient`; the
configured model is `openai/gpt-oss-120b` — an open-weights model **served by Groq**, not a call
to OpenAI. Note the account's tier allows 8,000 tokens/minute, roughly one agent turn per minute.

---

## Session Continuity Protocol

The repository is the source of truth, **not** a previous conversation. Every session starts here.

**Before writing any code:**

1. Read this file (`CLAUDE.md`) in full.
2. Read **`docs/PROJECT_STATE.md`** — the canonical current state and next safe action.
3. Read the relevant sections of `docs/implementation-status.md` for the milestone you are touching.
4. Read the ADRs that govern it (`docs/decisions/README.md` indexes them).
5. Run `git status`.
6. Inspect recent history (`git log --oneline -20`).
7. **Verify the current milestone against the actual source and tests** before coding. Do not accept
   a document's claim that something is done.
8. **Never assume previous conversation context is authoritative.** A summary, a recollection, or a
   prior session's claim is a hypothesis to check against the repository.

**After doing work:**

9. Update `docs/PROJECT_STATE.md` after any meaningful implementation.
10. Update `docs/implementation-status.md` when a milestone completes.
11. Create or update an ADR whenever an architectural decision changes. Supersede the old one
    explicitly; never leave two live decisions on the same question.
12. **Run the tests before claiming anything is complete.**
13. Record the test count and verification status in `docs/PROJECT_STATE.md`.
14. **Never proceed to the next milestone without satisfying the current one's exit criteria.**
    Code existing is not the same as a milestone being complete.

## Documentation roles

Each file has exactly one job. Keep them from drifting into each other.

| File | Role |
| --- | --- |
| `CLAUDE.md` | Persistent instructions and engineering rules for Claude Code. |
| `docs/PROJECT_STATE.md` | **Canonical current state and next action.** Wins over every other doc on questions of current state. |
| `docs/implementation-status.md` | Detailed milestone-by-milestone implementation history. |
| `docs/decisions/` | Architectural decisions and their rationale. |
| `docs/notes/deviations.md` | Implementation deviations, ambiguities, and their resolutions. |
| `docs/notes/open-questions-status.md` | Open questions and their current status. |
| `PROGRESS.md` | High-level human-readable snapshot only. **Must not contradict `PROJECT_STATE.md`.** |
| `architecture.md` | The specification. **Never edited.** |
| `docs/frontend/` | Frontend analysis and specification material. **Not evidence that anything is built.** |

The only project root is `L:\AI_COMMERCE`. `L:\RazorPay\backend` is an unrelated SQLite prototype —
never inspect, import, copy or depend on it.

---

## What this is

A conversational commerce agent for a merchant catalog (EASY BUY — electronics only, 200
products / 360 SKUs since 2026-09-05; see `docs/notes/deviations.md` D13), built on one
invariant that every part of the specification restates:

> **LLM proposes → application validates → user authorizes → Razorpay executes → system audits.**

`architecture.md` (16,737 lines, six parts) is the specification. It is **never edited**. Where it
leaves something open, states it two ways, or requires something it never defines, the resolution is
an ADR in `docs/decisions/` — read `docs/decisions/README.md` first, it indexes all nineteen.

**Current state lives in [`docs/PROJECT_STATE.md`](docs/PROJECT_STATE.md), not here.** That file
carries the milestone table, test counts and next action, and is updated after every meaningful
change. In summary: M0–M10, M12 and M13 are COMPLETE; M11 is code-complete but its live check is
unperformed; M14 is IN_PROGRESS (only F1's backend half); M15's backend scenarios pass. **M4-R**
(the locked Groq provider) is COMPLETE and live-verified, as is frontend phase F0.

The milestone plan is `docs/analysis/02-dependency-map.md`. Build one milestone at a time; the
specification is emphatic (D§39, A§58, F§37) that this must not be built in one pass, and the money
path must not be coded before its decisions exist.

## The frontend (M14, from F0)

Lives in `frontend/`, on Vite + React 18 + TypeScript (ADR-017). `cd frontend && npm run dev`.

**The agent chat runs on Assistant UI, and only its runtime** (ADR-019). `useLocalRuntime` with a
custom `ChatModelAdapter` whose `run()` is a plain `async` function returning one result — the
documented non-streaming pattern, because `POST /api/chat` answers once per turn and streaming is a
closed decision (ADR-010). **Do not run `npx assistant-ui@latest init`**: it targets Next.js and
installs via `shadcn`, neither of which this project uses. `recommendations[]`, the cart, the
approval dialog and the order page are ordinary components and stay that way; product cards are not
tool UI, because tools execute server-side.

**Money is a string and stays one.** `"999.00"`, never `999.00`. Nothing in the frontend sums,
multiplies or rounds a money value — totals come from the backend or they do not exist (ADR-008,
F§12). The `Money` Zod schema rejects a JSON number and an unscaled string, so a total can never
render as `1299`.

**Every response is parsed through a Zod schema** in `src/api/schemas.ts`. Contract drift becomes a
loud `MALFORMED_RESPONSE` at the fetch boundary instead of an `undefined` deep in a component.

**A business outcome is not a network error.** The backend answers HTTP 200 for any turn it
completed, *including* a policy refusal or an out-of-stock finding (ADR-010). `request()` throws only
for 4xx/5xx and transport failures, so recovery flows never land in a component's error branch.

**The error vocabulary is mirrored by hand and guarded.** `API_ERROR_CODES` in `schemas.ts` copies
F§25's eleven codes; `backend/tests/api/test_frontend_contract.py` fails if it ever diverges from
`app/agent/errors.py`, and also fails if a secret-bearing name appears in frontend source.

**No secret may ever reach frontend code**, including in a `VITE_`-prefixed variable — Vite inlines
those into the published bundle. The only credential that reaches the browser is the *public*
Razorpay key id, in a response body at checkout time.

⚠️ **Port 8000 may be occupied by an unrelated application on this machine** — see
`docs/PROJECT_STATE.md` §11. If the health panel reports a malformed response, check what is actually
listening before debugging anything else.

## Commands

Everything runs from `backend/`, using the virtualenv at `backend/.venv`.

```bash
cd backend
pip install -e ".[dev]"

# Database (required — see "PostgreSQL only" below)
docker compose up -d db          # from the repository root; also creates ai_commerce_test
alembic upgrade head
python -m app.seed.circuitcraft            # idempotent
python -m app.seed.circuitcraft --validate-only   # validates the seed file, touches no database
python -m app.seed.circuitcraft --summary         # row counts from the database

alembic upgrade head --sql       # render the whole schema as DDL without connecting
alembic downgrade base

uvicorn app.main:app --reload    # http://127.0.0.1:8000/api/health and /docs

python -m pytest
python -m pytest -m requires_db                        # only the live-database tests
python -m pytest tests/db/test_catalog_schema.py       # one file
python -m pytest -k test_price_round_trips_as_decimal  # one test

python -m ruff check .
python -m ruff format .
```

Tests needing PostgreSQL are marked `requires_db` and **skip with a visible reason** when
`TEST_DATABASE_URL` is unreachable. A run showing skips is an incomplete run, not a pass. Full suite
with a database: **1258 tests, all passing, none skipped**; 880 of those need no database.

This machine has neither Docker nor an installed PostgreSQL. The documented way around that — used
to verify M1, M3 and M5 through M10 — is a throwaway PostgreSQL 16.4 unpacked from the official Windows binary
archive into the session scratchpad (`initdb` + `pg_ctl` in user space, no installer, no service,
nothing written outside the temp directory), then `TEST_DATABASE_URL` pointed at it. See
`docs/implementation-status.md` §11.

## Rules that are not negotiable

These are the ones a well-meaning change is most likely to break.

**`architecture.md` is never edited.** Corrections and resolved ambiguities go to `docs/decisions/`
and are indexed in `docs/notes/deviations.md`.

**PostgreSQL only, in every environment including tests** (ADR-002). The schema depends on `UUID`,
`JSONB` and `TEXT[]`. `Settings` rejects any non-PostgreSQL `DATABASE_URL` outright. Never make a
`requires_db` test pass by pointing it at SQLite — a green run against a different engine proves
nothing. (`L:\RazorPay\backend`, outside this repo, is an unrelated SQLite prototype; do not use it.)

**Money is `Decimal` and `NUMERIC(12,2)`.** No `float` in any arithmetic, Pydantic field, JSON, or
fixture. Seed and API money is a **string** (`"999.00"`) because `json.loads` turns `999.00` into a
float before validation can intervene. Integer minor units exist only inside `app/payments/`,
converted by two functions in one module (ADR-008).

**Deterministic packages must not import `app.llm` or `app.agent`.** `app/services/`, `app/ranking/`,
`app/policy/` and `app/payments/` are the trusted side of the boundary.

**Model output is untrusted input.** A model-supplied `variant_id` or `sku` is a lookup key, never a
fact. No tool accepts a price. `create_order` is deliberately **not registered as a tool at all**
(ADR-009) — order creation is a user-initiated API path behind the Policy Engine.

## Architecture worth knowing before you edit

### Where authority lives

```
Claude → tool call → tool handler → service → repository → PostgreSQL
                                        ↓
                         ranking engine (deterministic, no model)
                                        ↓
                   cart → user approval → Policy Engine → order → Razorpay
                                                                     ↓
                                                    verified webhook → payment truth
```

PostgreSQL owns product facts. The ranking engine owns relevance. The Policy Engine owns whether
money may move. A verified Razorpay webhook owns whether it did. The model owns none of these.

### Three state machines that share value names

A recurring trap: `APPROVED`, `POLICY_VALIDATED` and `PAYMENT_CONFIRMED` appear in more than one
enum in the source document. They are kept as three separate enums, each owned by one table, and
**none is ever derived from another** (ADR-006, ADR-007):

| Enum | Owner | Read by |
| --- | --- | --- |
| Conversation state | `sessions.conversation_state` | the UI and the agent runtime |
| Approval status | `approvals.status` | the Policy Engine |
| Order state | `orders.status` | the Policy Engine, the webhook handler, the UI |

A session whose conversation state says `APPROVED` authorizes nothing. Only an `approvals` row does.

### Compatibility resolution (ADR-003) — the subtlest part of the catalog

The specification forbids the model from deciding compatibility, yet the model is what produces the
identifier string that gets matched. The pipeline closes that gap:

```
user text → [LLM] a phrase ("iPhone 16") → normalize_token() → resolve against
compatibility_targets → canonical id ("iphone_16") → query compatibility_rules
```

- `app/canonical.py` holds `normalize_token`. It handles case and punctuation only:
  `normalize_token("iphone16")` is `"iphone16"`, **not** `"iphone_16"`. That is precisely why
  `compatibility_targets.aliases` exists.
- `compatibility_targets.target_type` and `compatibility_rules.target_type` **mean different
  things**. The first classifies what the identifier *is* (`phone_model`, `laptop_model`,
  `device_port`); the second classifies how a product *relates* to it, and adds the broader `device`
  the specification uses for chargers. A query for "compatible with the phone `iphone_16`" matches
  rules whose `target_type` is in `('phone_model', 'device')`.
- Unresolvable, or ambiguous, means **ask the buyer**. Never guess, never fall back to substring
  matching, never drop the compatibility constraint to obtain results.
- `compatibility_rules.constraints` are predicates on the **product's own attributes**:
  `{"minimum_wattage": 20, "fast_charge": true}` means "provided this product supplies ≥20W and
  supports fast charging".

### The variant is the sellable unit

SKU, price, currency and stock live on `product_variants` / `inventory`, never on `products`. A
product is "what is this"; a variant is "which exact sellable version". Search returns one row per
variant.

### Hard constraints eliminate, they never score

Merchant, activity, category, budget, compatibility, required specification and inventory are
**filters applied before ranking** (ADR-005). There is no weight configuration in which a cheap
incompatible product can outrank a compatible one. Ranking weights and formulas are in ADR-004; the
engine is deterministic and the model never computes a score or writes a recommendation `reason`.

### The ranking engine (M3) — what will bite you

`app/ranking/` is **pure**: no session, no query, no clock, no randomness, no model. Inputs and
outputs are frozen domain values. Keep it that way — it is what makes ADR-004's exit test (the R§10
worked example, `tests/ranking/test_ranker.py`) an ordinary unit test, and it is why 880 of the 1258
tests need no database. `RecommendationService` is the only M3 code that opens a query.

**The R§10 worked example is the exit condition and it is exact.** Under the `explainability_demo`
profile, AeroCase Pro scores `0.796800` and ShieldCase Premium `0.786800` — the specification's own
`0.7968` and `0.7868`. If a change moves those numbers, the change is wrong, not the test.

**Scores are `Decimal`, quantized to six places.** A `float` total is not reproducible across
platforms, and RULE 8 requires determinism. Sorting is `(-final_score, price, sku)` — three keys,
because scores tie often on a small catalog and price ties across colours of one product.

**`price_denominator` returns `None` for degenerate sets** (empty, single candidate, all one price,
or a maximum of zero) and `price_score` answers `1.0` for it. That branch governs the *unbudgeted*
denominator only; a stated budget always uses R§8's formula, so a product priced exactly at the
budget scores `0.0` on purpose.

**No stated preferences scores `0.0`, not `1.0`** (ADR-004, A4). Ordering is unaffected — a constant
cannot reorder anything — but no candidate can then exceed the remaining weights. Anyone writing a
threshold against `FinalScore` has to know this.

**Weights live only in `app/ranking/weights.py`.** RULE 14. No scorer, aggregator or service
contains a number; they multiply by what a `WeightProfile` says. Profiles are validated to sum to
exactly `1`. `RANKING_PROFILE` is validated at startup, so a typo fails loudly instead of silently
reordering every result. The model may pick a profile **by name**; it must never emit a weight.

**Hard constraints eliminate and are checked without weights.** `apply_hard_constraints` takes no
profile argument at all — that is the structural form of ADR-005's promise that no configuration
lets a cheap incompatible product outrank a compatible one. Every candidate is evaluated against
every constraint, not stopped at the first failure, because deciding whether a rejection is an
honest *alternative* needs to know it failed only a relaxable one.

**Only `BUDGET` and `REQUIRED_SPECIFICATION` are relaxable.** Compatibility never is (a case for a
different phone is a wrong answer, not a lesser one), inventory never is (RULE 5 — an alternative
nobody can buy is not an alternative), category never is. Alternatives are re-scored with the budget
removed, or the clamp would flatten them all to zero and lose their order.

**`ProductRequirement.compatibility_target` is a `ResolvedTarget`, never a string.** That types the
ADR-003 pipeline shut: a device phrase the model wrote cannot reach the ranker, and resolution
failure stays a question for the buyer rather than becoming a no-match. `apply_hard_constraints`
raises if a requirement carries a target but no resolved compatible set was supplied — compatibility
must not be relaxable by omission.

**`RecommendationService._candidates` pushes only the category into SQL.** Budget, text and
attributes are deliberately left out: filtering budget in the query would leave the no-match path
with no real product to offer, and text is a relevance signal (R§9), not a constraint.

**`app/attributes.py` is the single meaning of "attribute satisfies expectation"** — shared by
compatibility rules, the required-specification constraint and the preference scorer. A missing
attribute always fails. Do not add a second implementation.

### The LLM layer (M4) — what will bite you

`app/llm/` is the other side of the boundary. Everything in it is **untrusted**: a `BuyerIntent` is
what the model believes the buyer asked for, a `ToolCall` is something the model would like to
happen, and neither carries a price, a SKU, a stock level or a compatibility fact.

**`client.py` is the only module allowed to import the model SDK** (ADR-015, ADR-018). An
AST-walking test asserts the importer list is exactly that one file. Everything else takes the
one-method `LLMClient` protocol, which is what makes all 201 LLM tests run with no key and no
network. The transport types in `models.py` are provider-agnostic by design (deviation A22),
so the concrete client class is the *only* provider-specific code in the application.

> Groq's API is **OpenAI-compatible**: `finish_reason` (not `stop_reason`), tools shaped as
> `{"type": "function", …}`, tool arguments as a JSON **string**, and usage under
> `prompt_tokens`/`completion_tokens`. Each of those was a real defect once; each now has a
> named regression test in `tests/llm/test_client.py`. The system prompt is the **first
> message**, not a top-level field — sending `system=` is silently ignored.

**No test may call a live model, ever.** Not marked, not skipped-when-absent. The model is faked at
the protocol (`tests/llm/conftest.py::FakeClient`, which replays a script and records payloads); the
SDK is faked only inside `tests/llm/test_client.py`, and those doubles raise the SDK's *real*
exception classes, because `_map_exception` dispatches on class identity.

**Extraction asks for text JSON, not a tool call, and that is deliberate.** Tool arguments arrive
from the SDK already JSON-decoded, so a budget of `1500.10` would be a `float` before this
application saw it — and `Decimal` built from a lossy float is still lossy. Text output goes through
`loads_decimal` with `parse_float=Decimal`. `Budget` rejects a `float` outright, so a shortcut around
this becomes a test failure rather than a wrong ceiling. Tool arguments have no such interception
point, which is why `tool_schemas._money_from_model` uses the bounded `Decimal(str(x))` conversion
instead.

**Carry-forward is by omission; removal is by `null`.** L§26 requires the intent to be updated across
turns and never defines "update". A top-level field the model leaves out inherits from the previous
intent; one it sets to `null` is cleared. `merge_intent` iterates `BuyerIntent.model_fields`, so a
field added later carries forward without anyone remembering to add it to a list.

**Malformed output gets one bounded repair and is never repaired by hand.** The extractor tells the
model what failed validation and asks once more. It does not coerce a type, fill a missing field, or
accept a bare intent object instead of the envelope — A§19 forbids executing raw model output, and a
"helpful" coercion is how a malformed call becomes a real one.

**Truncation, refusal and an unexpected tool call are failures, not empty intents**, and none is
retried: the same request truncates the same way, and the buyer is waiting.

**`create_order` is not in `TOOL_SCHEMAS` and must not be added.** Not registered-and-failing —
absent. `FORBIDDEN_TOOL_NAMES` and a standing test keep it out, and `validate_tool_arguments`
reports a call to it as *forbidden* rather than *unknown*, so the attempt is visible in logs.

**There are no tool handlers in `app/llm/`.** Binding a tool to a service is the agent runtime's job
(M5, AGENT-02). `tests/llm/test_boundaries.py` fails if a function here is named after a tool, and if
anything here imports a service, a repository or SQLAlchemy.

**Prompts are Markdown files with per-file versions.** `PROMPT_VERSIONS` has an entry per `.md`, and
a test asserts every file on disk has one — an unversioned prompt makes every trace that used it
unattributable. The leading `<!-- -->` block in each file is editorial and is stripped before
sending. Prompt tests assert *auditability*, never model behaviour: per L§29 and ADR-009, the wording
makes the agent behave well and is not what stops it behaving badly.

### The agent runtime (M5) — what will bite you

`app/agent/` is the only package that imports both `app.llm` and a service. That is its job, and a
standing guard asserts it is the *only* one: a second package touching both sides would be a second
door onto the boundary, and only one of them has been reviewed.

**`recommendations[]` is built from `TurnMemory`, never from the model's reply.** The tools write
what `RecommendationService` returned; the response builder serializes that. A model that describes
a product it was never shown produces a turn whose structured half simply does not contain it — and
a test scripts exactly that. Prose goes in `message`; nothing is parsed out of it (F§9).

**`create_order` is absent four ways**, and each is a separate test: not in the registry, not in
`HANDLERS`, no module named for it under `app/agent/tools/`, and `build_registry` raises if asked.
The executor reports a call to it as **forbidden**, not unknown, so an injection attempt is legible
in a log instead of looking like a typo.

**The executor implements A§19 once, and the order of its stages matters.** The call limit is
checked *before* the registry lookup, so a call that cannot be afforded is never validated,
authorized or run — a test asserts this using a nonexistent tool, which would otherwise answer
`UNKNOWN_TOOL`. A failed call still consumes one of the eight, or a model making only bad calls
would loop forever.

**Tool errors are returned, never raised.** `ToolExecutor.execute` always yields a payload. One
conversion site means the rule can only be wrong in one place. An unexpected exception becomes
`INTERNAL_ERROR` with a generic sentence; its text never reaches the model (F§25).

**Two error vocabularies, one mapping.** `ToolErrorCode` is internal and may grow; `ApiErrorCode` is
F§25's closed eleven and may not. `to_api_code` is the only bridge, and an internal failure never
narrows onto a business code — telling a client to run an out-of-stock recovery flow for a registry
bug would be worse than a generic error.

**Only LOW-tier tools run.** The tier check is real, not implied by which tools happen to be
registered: a test wires a MEDIUM tool in by hand and asserts it is refused. `propose_cart` has had
a schema since M4 and gets a handler in M7; `build_registry` refuses to expose a tool it cannot
execute.

**`sessions` and `session_messages` arrived in M5, not M6** (deviation A28). C3 is closed as
PostgreSQL and AGENT-01 is the task that closes it. The other nine ADR-006 tables are still M6, and
the guard in `test_catalog_schema.py` was narrowed to those nine *and* paired with a test asserting
these two are present — so the narrowing is a statement, not a hole.

**`ConversationState` lives in `app/domain/`, not `app/agent/`.** The ORM model builds its `CHECK`
from it and the runtime drives transitions with it; neither layer may depend on the other. All
twenty values are defined now because widening a `CHECK` costs a migration, and `REACHABLE_FROM`
records which milestone first produces each.

**The seeded-database fixtures are module-scoped, and that is load-bearing.**
`tests/db/test_catalog_integrity.py` downgrades to base at its own teardown — proving a fresh
database can be built from the migrations is the point of that module — so anything running
afterwards must re-ensure the schema. A session- or package-wide cache ensures it once, before that
teardown, and every later module then queries a database with no tables.

**The seed's category slugs are `phone_case`, `charger`, `usb_cable`, `earbuds`, `smartphone`,**
**`laptop`, `monitor`, … — not `phone-cases`.** `search_catalog` and `get_compatible_products` validate the slug against the
merchant's real categories and answer `CATEGORY_NOT_FOUND` for anything else, so a wrong slug in a
test looks like a broken tool.

## Working on the schema and migrations

**Alembic applies the metadata naming convention on top of names you pass.** `CheckConstraint` in a
migration must therefore take the **bare** name (`"price_is_not_negative"`), not the prefixed one, or
you get `ck_products_ck_products_...`. Primary keys, unique constraints and foreign keys take their
full names.

**`tests/db/test_migrations.py` diffs the rendered migration DDL against the compiled model
metadata**, constraint names included. Change a model without mirroring it in a migration and that
test fails. It runs without a database, so there is no excuse for drift.

**Composite merchant-scoping foreign keys create ambiguous relationships.** `products` has two FK
paths to `categories` (the plain `category_id` key plus the composite merchant-scoping key), so ORM
relationships across those pairs need an explicit `foreign_keys=`. SQLAlchemy configures mappers
lazily, so the error only appears when something queries; `test_every_orm_relationship_resolves`
forces configuration to catch it offline.

**Four migrations, and the split is deliberate.** `0001` is exactly the seven tables the
specification defines; `0002` adds `compatibility_targets` (ADR-003); `0003` adds the two session
tables M5 needed; `0004` adds ADR-006's remaining nine. ADR-006 calls its own migration `0003`, which
is now taken — the numbering follows the order things were built, not the order they were designed.

**Migration `0001` is exactly the seven tables the specification defines.** `compatibility_targets`
is in `0002` on purpose, so the specified schema stays auditable on its own. A test enforces the
split. Commerce tables (ADR-006) belong to M6 and must not appear before then — a test enforces that
too.

**Seeded rows have deterministic UUIDv5 identifiers** (`app/identifiers.py`), which is what makes
seeding idempotent and lets tests name a row without querying for it. `DEFAULT_MERCHANT_ID` is
derived the same way, so merchant scoping is configuration rather than discovery.

**The seed is electronics only and is pruned, not just upserted.** `--prune` on the loader removes
merchant rows the seed file no longer contains, deactivating rather than deleting anything an order
or a cart references (deviation D13). Seeding alone never deletes, which is why a removed category
survived every re-seed until this existed.

**Seed data is authored under a claims rule**: fictional CircuitCraft own-brand items described only
by structural attributes (material, colour, wattage, port type, length, capacity, battery hours,
ANC). No certifications, ratings, review counts, test results, warranty terms, or real third-party
brand names. Values the specification does supply are reproduced verbatim.

The catalog is deliberately shaped so each filter is separately testable: an out-of-stock variant, an
iPhone 15 case that must be excluded from iPhone 16 searches, products either side of the ₹1,500
line, earbuds with no compatibility rules, and `pixel_9` as a *resolvable* device with zero
compatible products — the no-match path as distinct from an unresolved device.

## Payments, when you get there

Not implemented. Read ADR-011 through ADR-014 before writing any of it.

- The Policy Engine re-reads price and stock **live, inside the order transaction**, never from
  `cart_items.unit_price_snapshot`. It evaluates all ten rules rather than stopping at the first
  failure, and returns machine-readable reason codes.
- The internal order is committed **before** Razorpay is called.
- Webhook verification runs against the **raw request body**, captured before parsing — so that
  route must not bind a Pydantic body model. Deduplication is a `UNIQUE` constraint, not a
  read-then-write check.
- A price change in **either direction** invalidates an approval and requires reconfirmation with a
  fresh idempotency key. Price drift, out-of-stock, policy failure and payment failure all recover
  through the same path.
- Razorpay test doubles live only under `backend/tests/fixtures/`, never in application code.

## Where the decisions are

| Question | Read |
| --- | --- |
| Why is it built this way at all? | `docs/decisions/ADR-001-architecture-invariant.md` |
| What was the repo like before, and how was it verified? | `docs/implementation-status.md` |
| Where does this depart from the specification, and why? | `docs/notes/deviations.md` |
| What is the build order? | `docs/analysis/02-dependency-map.md` |
| What did the specification leave open? | `docs/analysis/03-open-questions.md` |
