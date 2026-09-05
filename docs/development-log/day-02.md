# Day 02 — 31 August 2026

**Date:** 31 August 2026
**Time:** 19:50 – 20:02 IST (+0530), from commit timestamps `10c75c0` … `3b483ed`

A short working period, but it lands the two pieces the whole architecture is built to keep
apart: the deterministic ranking engine, and the LLM layer.

## What Was I Trying to Do?

Build recommendation ranking as pure, testable code — no model anywhere near it — and then
build the LLM layer separately, on the other side of a boundary I could enforce with a test.

## Question

If the model is not allowed to decide which product wins, what is?

And the second question, which turned out to matter more: how do I test an LLM layer without
ever calling one?

## Answer

`app/ranking/` is pure. No session, no query, no clock, no randomness, no model. Inputs and
outputs are frozen domain values. That is what makes the specification's own worked example
(R§10) an ordinary unit test.

`app/llm/` is the untrusted side. `client.py` is the only module allowed to import the model
SDK, and an AST-walking test asserts the importer list is exactly that one file. Everything
else takes a one-method `LLMClient` protocol, which is what lets the whole LLM suite run with
no key and no network.

## Why?

Hard constraints eliminate; they never score. Merchant, activity, category, budget,
compatibility, required specification and inventory are filters applied *before* ranking
(ADR-005). There is no weight configuration in which a cheap incompatible product outranks a
compatible one — and `apply_hard_constraints` takes no profile argument at all, which is the
structural form of that promise.

For the LLM layer, ADR-015 is the argument: a live smoke test tells you the call succeeded, not
that the mapping was right. The model is faked at the *protocol* (`tests/llm/conftest.py`),
and the SDK is faked only inside `tests/llm/test_client.py` — where the doubles raise the SDK's
real exception classes, because `_map_exception` dispatches on class identity.

## What Changed?

- `app/ranking/`: `filters.py`, `scorers.py`, `ranker.py`, `weights.py`, `explain.py`,
  `combinations.py`, plus `app/attributes.py` and `RecommendationService` (`10c75c0`)
- Ranking tests, including the R§10 worked example (`78d5452`)
- `app/llm/`: `client.py`, `extractor.py`, `models.py`, `schemas.py`, `tool_schemas.py`, and the
  two versioned Markdown prompts (`4aa19b8`)
- ADR-015 — the LLM test seam — written with the layer it governs (`4aa19b8`)
- LLM tests: client, extractor, schemas, tool schemas, prompts, boundaries (`7d96053`)
- A **provisional** `GroqClient` alongside the protocol, committed as provisional because a Groq
  key was available on this machine and an Anthropic key was not (`3b483ed`)

Two rules from this day that are still load-bearing:

**`create_order` is not in `TOOL_SCHEMAS` and must not be added.** Not registered-and-failing —
absent. `FORBIDDEN_TOOL_NAMES` and a standing test keep it out (ADR-009).

**Extraction asks for text JSON, not a tool call.** Tool arguments arrive from the SDK already
JSON-decoded, so a budget of `1500.10` would be a `float` before this application saw it, and a
`Decimal` built from a lossy float is still lossy. Text output goes through `loads_decimal` with
`parse_float=Decimal`.

## Problem I Hit

No confirmed development bug established for this period from repository evidence. The defects
that the provisional Groq client contained were found later, in the review that removed it — see
Day 03.

## What I Tried

The scoring formulas and weights are ADR-004's, not invented here. The R§10 worked example is
the exit condition and it is exact: under the `explainability_demo` profile, AeroCase Pro scores
`0.796800` and ShieldCase Premium `0.786800`, matching the specification's own `0.7968` and
`0.7868`. Scores are `Decimal`, quantized to six places — a `float` total is not reproducible
across platforms.

## What Worked

M3 verified: **520 tests pass, 0 fail, 0 skip** (`docs/implementation-status.md`, M3 section).
M4 verified: **719 tests pass, 0 fail, 0 skip**, 574 of them needing no database.

The boundary test earns its place immediately: `tests/llm/test_boundaries.py` fails if a function
in `app/llm/` is named after a tool, or if anything there imports a service, a repository or
SQLAlchemy.

## What Did Not Work?

The provisional Groq client (`3b483ed`) was committed knowing it was unverified. It did not
survive the next working period. Its removal and the reasons are Day 03.

## Decision

**Ranking is deterministic and lives outside the model.** See ADR-004 (weights and formulas) and
ADR-005 (hard constraints eliminate, they never score).

**No test may call a live model, ever.** Not marked, not skipped-when-absent. See ADR-015.

## Testing

```
python -m pytest        # M3: 520 passed;  M4: 719 passed, 0 failed, 0 skipped
python -m pytest tests/ranking/test_ranker.py   # the R§10 worked example
```

## Result

The engine that chooses products and the layer that talks to a model both exist, with a test
that will fail if either reaches into the other. Nothing is wired together yet — there is no
agent runtime, so no tool has a handler.

## What I Learned

"One importer of *this* SDK" is not the same claim as "one model SDK". The single-importer guard
for the Anthropic SDK stayed green for the entire life of the Groq client, because Groq is not
the Anthropic SDK. That hole was only visible once a second provider existed.

## Remaining Work

- Agent runtime and tool handlers (M5)
- The provider question, still unresolved

## Evidence

| Kind | Reference |
| --- | --- |
| Commits | `10c75c0`, `78d5452`, `4aa19b8`, `7d96053`, `b5b4103`, `3b483ed` |
| Tests | `tests/ranking/test_ranker.py`, `tests/llm/test_boundaries.py`, `tests/llm/test_client.py` |
| Docs | `docs/decisions/ADR-015-llm-test-seam.md`, `docs/implementation-status.md` M3 and M4 sections |
