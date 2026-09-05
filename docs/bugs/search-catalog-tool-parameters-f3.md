# Bug — Undescribed Tool Schema Treated Hard Search Requirements as Soft Preferences (F-3)

**Date:** September 5, 2026  
**Time:** 08:41:18 +0530

### Question

When a buyer explicitly specifies a technical requirement such as "earbuds with noise cancelling", does the AI agent translate this into an eliminating constraint in `search_catalog`, or does it treat it as a soft search term?

### What I Expected

I expected the model to call `search_catalog` with `category="earbuds"` and `attributes={"anc": true}`, so that the database and ranking pipeline strictly eliminated non-ANC models before ranking the remainder.

### What Actually Happened

During live evaluation on test case `spec_004`, the real model called `search_catalog` with:
```json
{
  "query": "earbuds with noise cancelling",
  "category": "earbuds",
  "attributes": {}
}
```
Because `attributes` was passed as empty, the search service treated "noise cancelling" solely as a text similarity signal. The catalog contained two ANC variants (SonicBuds Pro) and three non-ANC variants (AirFlow Basic, AirFlow Sport). Because price is a 30% ranking factor, the cheaper non-ANC earbuds scored higher than the ANC earbuds!

To make matters worse, the model then hallucinated in its natural language prose:
*"Here are three great noise-cancelling earbuds for you..."*
and recommended three non-ANC earbuds to the buyer!

Additionally, on another turn, the model volunteered `"currency": "USD"`, which was promptly rejected with a 422 error because the merchant's currency is strictly `INR`.

### Why Was This a Problem?

This was a major product integrity failure. A buyer explicitly asking for noise-cancelling headphones was recommended cheaper models that physically lacked active noise cancellation, with the assistant falsely reassuring the buyer that they had ANC.

### Root Cause

The root cause was not model stupidity; it was an underspecified tool schema in `app/llm/tools/definitions.py`.
The schema for `search_catalog` provided no descriptions for its fields. In particular:
1. `attributes` was defined as an empty JSON schema `{"type": "object"}` with title `"Attributes"`. There was no documentation indicating that `attributes` is an **eliminating hard constraint** that filters the catalog, nor did it document what attribute keys exist for this merchant (e.g. `anc`, not `noise_cancelling`).
2. `currency` was left as an unconstrained string, allowing the model to hallucinate `"USD"`.

Because the model had no idea what attribute keys the merchant tracked, it could not guess that `anc: true` was the filter key.

### Decision

We decided to fix this in the schema rather than through prompt engineering (per ADR-009: prompts are not controls; schemas and validators are).
We enriched the tool schema dynamically with:
1. Clear docstrings explaining that `attributes` is an eliminating filter.
2. A list of known valid attribute keys extracted directly from the merchant's active catalog.
3. An explicit enum for `currency` pinned to the merchant's configured currency (`INR`).

### Fix

In commit `98b1100`:
- Updated `app/llm/tools/definitions.py` to inject dynamic descriptions into `search_catalog`.
- Added `tests/llm/test_tool_schemas.py` tests asserting that the `attributes` parameter description explains its filtering semantics and enumerates the merchant's attributes.
- Constrained `currency` to `Literal[merchant_currency]`.

### Verification

Re-evaluated live on Groq with prompt: *"earbuds with noise cancelling"*.
The model emitted `search_catalog(category="earbuds", attributes={"anc": true})`.
The catalog returned only the two SonicBuds Pro ANC variants. The non-ANC earbuds were eliminated, and the prose described only the genuine ANC models.

### Result

PASS. Technical requirements eliminate non-matching products by construction.

### Evidence

- Git commit: `98b1100 fix(llm): describe search_catalog's own parameters (F-3)`
- File: [`backend/app/llm/tools/definitions.py`](file:///l:/AI_COMMERCE/backend/app/llm/tools/definitions.py)
- Evaluation case: [`backend/tests/evals/test_commerce_evals.py::test_case[spec_004]`](file:///l:/AI_COMMERCE/backend/tests/evals/test_commerce_evals.py)
- Documented in [`docs/EVALUATION-REPORT.md`](file:///l:/AI_COMMERCE/docs/EVALUATION-REPORT.md) §20a.
