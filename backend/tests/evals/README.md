# The commerce evaluation suite

270 cases that ask one question in many ways: **can anything the model does
break the invariant?**

> LLM proposes → application validates → user authorizes → Razorpay executes →
> system audits.

The suite is not a benchmark of the model. It is a test of the boundary the
model sits behind.

---

## What is actually under test

Everything except two things runs for real: the agent runtime, the tool
registry, the A§19 executor, the catalogue and inventory services, the
deterministic ranking engine, the cart, the approval service, the Policy
Engine, `OrderService`, and the MCP server — all against PostgreSQL with the
seeded catalogue.

The two exceptions are the seams the rest of the repository already draws:

| Faked | At | Why |
| --- | --- | --- |
| The model | the `LLMClient` protocol (ADR-015) | No test may call a live model, ever. |
| The payment provider | the `RazorpayApi` protocol (ADR-011) | Doubles live in `tests/fixtures/`, never in application code. |

**Scripting the model is not a limitation here — it is the method.** A case
declares a `model_plan`, and several plans are deliberately those of a model
that has been fully captured by an injected instruction: it calls
`create_order`, it passes a price to `propose_cart`, it invents a SKU, it loops
past the call budget. A suite that waited for a live model to attempt those
would mostly be measuring the model's luck. What is graded is what the
application did about it.

## The catalogue is the source of truth, at run time

No expectation in `commerce_eval_cases.json` names a price, a stock level or a
winning product. `catalog_facts.py` reads all of that from PostgreSQL when the
suite runs, through the same services the application uses, and the graders can
only ask the database whether what the agent said is true.

The case file *is* generated — `build_cases.py` reads every SKU, slug and
compatibility target out of `app/seed/data/catalog.json` and fails loudly on a
name that is not there — so a renamed row breaks the build rather than quietly
turning a case into a tautology.

```
python -m tests.evals.build_cases        # regenerate commerce_eval_cases.json
```

## Running it

```bash
cd backend

# As tests. One test per case; fails the build on any failure.
python -m pytest tests/evals

# As a report. Writes evaluation-results.json and prints the scores.
python -m tests.evals.commerce_eval_runner
python -m tests.evals.commerce_eval_runner --filter compatibility
python -m tests.evals.commerce_eval_runner --filter drift --limit 5
```

Both need `TEST_DATABASE_URL` pointing at a PostgreSQL with the schema at head
and the catalogue seeded. ADR-002: never a different engine, not even to make
the suite runnable.

Each case runs in its own transaction, rolled back afterwards, with
`join_transaction_mode="create_savepoint"` so application code committing its
own unit of work behaves exactly as in production while nothing survives.
Several cases move a price or empty a shelf on purpose; none of it may be
visible to the next case.

## The files

| File | Role |
| --- | --- |
| `commerce_eval_cases.json` | The dataset. Generated; do not hand-edit. |
| `build_cases.py` | Generates it from the seeded catalogue. |
| `catalog_facts.py` | What the evaluator is allowed to know, read from the database. |
| `scripted_model.py` | An `LLMClient` that replays a case's `model_plan`. |
| `harness.py` | Drives one case through the agent, MCP, or the money path. |
| `observation.py` | What a case produced, in one shape every check can read. |
| `graders.py` | The checks. Every verdict in the suite comes from here. |
| `commerce_eval_runner.py` | Runs and scores; the CLI and the pytest module share it. |
| `test_commerce_evals.py` | The pytest entry point, plus guards on the dataset itself. |
| `live_eval.py` | The opt-in live tier. Not a test - see below. |
| `evaluation-results.json` | The last offline run, in full. What `docs/EVALUATION-REPORT.md` quotes. |
| `live-results.json` | The last live sample. Overwritten by each run, including one the token quota blocked. |
| `f3-verification.json` | Finding F-3, before and after: the tool call the live model made each time, executed against the real catalogue. |

## The three surfaces

`mode` selects the runner.

* **`agent`** — one to many turns through `AgentRuntime`. A multi-turn case
  reuses one session id and gives each turn its own scripted model with no
  memory of the last, so a case that passes proves the *application* carried
  the state.
* **`mcp`** — the ADR-024 surface, driven through `call_tool` the way an
  external AI buyer drives it, including a `drift` step that moves the
  catalogue between two of its calls.
* **`commerce`** — cart, approval, drift, the Policy Engine, order creation and
  idempotency. The drift is applied *after* the approval and the cart is
  deliberately not refreshed, so what is tested is `OrderService` re-reading
  live price and stock inside the order transaction.

## Adding a case

Add it to `build_cases.py`, regenerate, run it. A case needs:

* a `prompt`, an `expected_intent`, the `expected_constraints` it must respect,
  an `expected_behavior` and a `forbidden_behavior` list — the judgement half,
  which cannot be derived from the catalogue;
* `checks`, each naming a function in `graders.CHECKS`;
* a `severity_if_failed` (P0 money/safety · P1 commerce correctness · P2 agent
  quality · P3 cosmetic) and the `dimensions` it counts toward.

`test_the_case_file_is_internally_consistent` and
`test_every_p0_case_asserts_something_about_money` guard the dataset offline, so
a case that names a check that does not exist, or claims P0 while asserting
nothing about money, fails without a database.

## The live tier

`python -m tests.evals.live_eval` runs the same cases through `POST /api/chat`
against a running backend and the **real model**, applying the same graders to
the answer. It is an operator script, not a test: ADR-015 says no test may call
a live model, ever.

It exists because the offline suite has one structural blind spot. Scripting the
model fixes the tool arguments, so the suite can prove the application enforces a
requirement it is *given* - and can never observe whether a real model gives it
one. That gap is where the sharpest finding in
`docs/EVALUATION-REPORT.md` came from (F-3): asked for "noise-cancelling
earbuds", the live agent returned three real, in-stock, non-ANC earbuds, because
it put "noise cancelling" in `search_query` (a relevance signal) rather than in
`attributes` (which eliminates).

```bash
python -m tests.evals.live_eval \
    --base-url http://127.0.0.1:8004 \
    --cases budget_001,compat_001,spec_004 --pace 100
```

**Pace it, and expect to be refused.** The account is on Groq's `on_demand`
tier: **8,000 tokens per minute** and **200,000 per day**. One agent turn is two
model calls totalling about **9,200 tokens**, so a whole turn does not fit the
per-minute cap *at any pace* - the two calls happen seconds apart. And at ~4,400
tokens a call the daily budget is about 45 calls, which a morning of evaluation
exhausts.

That is why `--tool-call-only` exists: one model call per case (~4,400 tokens),
with the application executing what the model asked for and the real results
graded. It is a narrower observation than a whole turn and is labelled
`live_tool_call`, but it covers the half the offline suite cannot see - which
tool the model picks and with which arguments.

A refused call is reported as `rate_limited_or_unavailable`, never as a failure:
a model that never answered has not got anything wrong.

Checks with no observable form in a `ChatResponse` (a specific `ToolErrorCode`,
the alternatives payload, the eight-call bound) are skipped by name rather than
approximated, and each run records what it skipped.

## Recorded findings

Two cases fail against the system as it stands, and both demonstrate one thing:
the assistant's prose is not validated against the catalogue. They are marked
`xfail(strict=True)` in `test_commerce_evals.py` with the finding written out.

That is a **recorded open defect, not a weakened check**. The checks are
untouched, the CLI runner still counts them as failures in the report, and
`strict=True` means a case that starts passing fails the build until its entry
is removed - so a fix cannot land silently and a finding cannot outlive the
behaviour it describes. `test_every_known_finding_names_a_real_case` guards the
list against drift.

## The one rule

**Never loosen a check to make a case pass.** If a check fires, the finding is
real until someone shows the check is wrong about the *architecture*, not about
the outcome. The suite exists to find weaknesses; an evaluator that can be
negotiated with finds none.
